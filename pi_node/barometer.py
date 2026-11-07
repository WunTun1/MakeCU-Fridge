"""Grove barometer over I2C, auto-detecting which Bosch chip is on the board.

Seeed sells "Grove - Barometer Sensor" with several different chips. The
chip-ID register (0xD0) tells them apart:
  0x58 BMP280  (temperature + pressure)
  0x60 BME280  (temperature + pressure + humidity)
  0x55 BMP180 / BMP085 (temperature + pressure, older register layout)

Compensation formulas are the floating-point / integer reference algorithms
from the Bosch datasheets; they're pure functions so tests can check them
against the datasheets' worked examples.
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass

try:
    from smbus2 import SMBus
except ImportError:  # pragma: no cover - only on the Pi
    SMBus = None

I2C_BUS = 1
CANDIDATE_ADDRESSES = (0x77, 0x76)
REG_CHIP_ID = 0xD0
CHIP_BMP280 = {0x56, 0x57, 0x58}
CHIP_BME280 = {0x60}
CHIP_BMP180 = {0x55}


@dataclass
class Reading:
    temperature_c: float
    pressure_hpa: float
    humidity_pct: float | None = None


# ----------------------------------------------------------- BMP280 / BME280
@dataclass
class Bmx280Calib:
    T1: int
    T2: int
    T3: int
    P1: int
    P2: int
    P3: int
    P4: int
    P5: int
    P6: int
    P7: int
    P8: int
    P9: int
    H1: int = 0
    H2: int = 0
    H3: int = 0
    H4: int = 0
    H5: int = 0
    H6: int = 0


def bmx280_temperature(adc_t: int, c: Bmx280Calib) -> tuple[float, float]:
    """Returns (temperature °C, t_fine). t_fine feeds the pressure/humidity math."""
    var1 = (adc_t / 16384.0 - c.T1 / 1024.0) * c.T2
    var2 = ((adc_t / 131072.0 - c.T1 / 8192.0) ** 2) * c.T3
    t_fine = var1 + var2
    return t_fine / 5120.0, t_fine


def bmx280_pressure_pa(adc_p: int, t_fine: float, c: Bmx280Calib) -> float:
    var1 = t_fine / 2.0 - 64000.0
    var2 = var1 * var1 * c.P6 / 32768.0
    var2 = var2 + var1 * c.P5 * 2.0
    var2 = var2 / 4.0 + c.P4 * 65536.0
    var1 = (c.P3 * var1 * var1 / 524288.0 + c.P2 * var1) / 524288.0
    var1 = (1.0 + var1 / 32768.0) * c.P1
    if var1 == 0:
        return 0.0
    p = 1048576.0 - adc_p
    p = (p - var2 / 4096.0) * 6250.0 / var1
    var1 = c.P9 * p * p / 2147483648.0
    var2 = p * c.P8 / 32768.0
    return p + (var1 + var2 + c.P7) / 16.0


def bme280_humidity(adc_h: int, t_fine: float, c: Bmx280Calib) -> float:
    h = t_fine - 76800.0
    h = (adc_h - (c.H4 * 64.0 + c.H5 / 16384.0 * h)) * (
        c.H2 / 65536.0 * (1.0 + c.H6 / 67108864.0 * h * (1.0 + c.H3 / 67108864.0 * h))
    )
    h = h * (1.0 - c.H1 * h / 524288.0)
    return max(0.0, min(h, 100.0))


# ---------------------------------------------------------- BMP180 / BMP085
@dataclass
class Bmp180Calib:
    AC1: int
    AC2: int
    AC3: int
    AC4: int
    AC5: int
    AC6: int
    B1: int
    B2: int
    MB: int
    MC: int
    MD: int


def _tdiv(a: int, b: int) -> int:
    """C-style integer division (truncates toward zero), as in Bosch's reference code."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def bmp180_compensate(ut: int, up: int, c: Bmp180Calib, oss: int = 0) -> tuple[float, float]:
    """Returns (temperature °C, pressure Pa)."""
    x1 = ((ut - c.AC6) * c.AC5) >> 15
    x2 = _tdiv(c.MC << 11, x1 + c.MD)
    b5 = x1 + x2
    temperature = ((b5 + 8) >> 4) / 10.0

    b6 = b5 - 4000
    x1 = (c.B2 * ((b6 * b6) >> 12)) >> 11
    x2 = (c.AC2 * b6) >> 11
    x3 = x1 + x2
    b3 = _tdiv(((c.AC1 * 4 + x3) << oss) + 2, 4)
    x1 = (c.AC3 * b6) >> 13
    x2 = (c.B1 * ((b6 * b6) >> 12)) >> 16
    x3 = ((x1 + x2) + 2) >> 2
    b4 = (c.AC4 * ((x3 + 32768) & 0xFFFFFFFF)) >> 15
    b7 = ((up - b3) & 0xFFFFFFFF) * (50000 >> oss)
    p = (b7 * 2) // b4 if b7 < 0x80000000 else (b7 // b4) * 2
    x1 = (p >> 8) * (p >> 8)
    x1 = (x1 * 3038) >> 16
    x2 = (-7357 * p) >> 16
    p = p + ((x1 + x2 + 3791) >> 4)
    return temperature, float(p)


# ------------------------------------------------------------------- driver
class Barometer:
    def __init__(self, address: int | None = None):
        if SMBus is None:
            raise RuntimeError("smbus2 not installed — pip install smbus2 (and enable I2C with raspi-config)")
        self.bus = SMBus(I2C_BUS)
        self.address, self.chip_id = self._detect(address)
        if self.chip_id in CHIP_BMP180:
            self._init_bmp180()
        else:
            self._init_bmx280()

    def _detect(self, address: int | None) -> tuple[int, int]:
        for addr in ([address] if address is not None else CANDIDATE_ADDRESSES):
            try:
                chip = self.bus.read_byte_data(addr, REG_CHIP_ID)
            except OSError:
                continue
            if chip in CHIP_BMP280 | CHIP_BME280 | CHIP_BMP180:
                return addr, chip
        raise RuntimeError(
            "No supported barometer found on I2C bus 1 (tried 0x77/0x76). Check `i2cdetect -y 1`, "
            "and that the chip printed on the board is a BMP280, BME280, BMP180, or BMP085."
        )

    @property
    def chip_name(self) -> str:
        if self.chip_id in CHIP_BME280:
            return "BME280"
        if self.chip_id in CHIP_BMP180:
            return "BMP180/BMP085"
        return "BMP280"

    def _init_bmx280(self) -> None:
        raw = bytes(self.bus.read_i2c_block_data(self.address, 0x88, 24))
        t1, t2, t3, p1, p2, p3, p4, p5, p6, p7, p8, p9 = struct.unpack("<HhhHhhhhhhhh", raw)
        self.calib = Bmx280Calib(t1, t2, t3, p1, p2, p3, p4, p5, p6, p7, p8, p9)
        if self.chip_id in CHIP_BME280:
            self.calib.H1 = self.bus.read_byte_data(self.address, 0xA1)
            h = bytes(self.bus.read_i2c_block_data(self.address, 0xE1, 7))
            self.calib.H2 = struct.unpack("<h", h[0:2])[0]
            self.calib.H3 = h[2]
            self.calib.H4 = struct.unpack("b", h[3:4])[0] * 16 | (h[4] & 0x0F)
            self.calib.H5 = struct.unpack("b", h[5:6])[0] * 16 | (h[4] >> 4)
            self.calib.H6 = struct.unpack("b", h[6:7])[0]
            self.bus.write_byte_data(self.address, 0xF2, 0x01)  # humidity x1 (must precede ctrl_meas)
        self.bus.write_byte_data(self.address, 0xF5, 0xA0)  # 1s standby, no IIR filter
        self.bus.write_byte_data(self.address, 0xF4, 0x27)  # temp x1, pressure x1, normal mode
        time.sleep(0.05)

    def _init_bmp180(self) -> None:
        raw = bytes(self.bus.read_i2c_block_data(self.address, 0xAA, 22))
        self.calib180 = Bmp180Calib(*struct.unpack(">hhhHHHhhhhh", raw))

    def read(self) -> Reading:
        if self.chip_id in CHIP_BMP180:
            return self._read_bmp180()
        data = self.bus.read_i2c_block_data(self.address, 0xF7, 8)
        adc_p = (data[0] << 12) | (data[1] << 4) | (data[2] >> 4)
        adc_t = (data[3] << 12) | (data[4] << 4) | (data[5] >> 4)
        temp, t_fine = bmx280_temperature(adc_t, self.calib)
        pressure = bmx280_pressure_pa(adc_p, t_fine, self.calib)
        humidity = None
        if self.chip_id in CHIP_BME280:
            humidity = bme280_humidity((data[6] << 8) | data[7], t_fine, self.calib)
        return Reading(temp, pressure / 100.0, humidity)

    def _read_bmp180(self) -> Reading:
        self.bus.write_byte_data(self.address, 0xF4, 0x2E)
        time.sleep(0.005)
        msb, lsb = self.bus.read_i2c_block_data(self.address, 0xF6, 2)
        ut = (msb << 8) | lsb
        self.bus.write_byte_data(self.address, 0xF4, 0x34)  # oss = 0
        time.sleep(0.005)
        msb, lsb, xlsb = self.bus.read_i2c_block_data(self.address, 0xF6, 3)
        up = ((msb << 16) | (lsb << 8) | xlsb) >> 8
        temp, pressure = bmp180_compensate(ut, up, self.calib180)
        return Reading(temp, pressure / 100.0)
