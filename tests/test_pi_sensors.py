from types import SimpleNamespace

from pi_node import sensors
from pi_node.barometer import Reading
from pi_node.hx711 import Calibration


class _Cell:
    def __init__(self, raw):
        self.raw = raw

    def read_raw(self, samples: int = 3):
        return self.raw


class _GPIO:
    HIGH = 1

    def __init__(self, level):
        self.level = level

    def input(self, pin):
        return self.level


def _hw(tmp_path, raw=10_000, pressed=True, baro=True):
    cfg = SimpleNamespace(hx711_pins=((16, 17),), door_switch_pin=5, door_closed_when_pressed=True, light_adc_channel=0)
    baro_dev = SimpleNamespace(chip_name="BME280", address=0x76, read=lambda: Reading(3.8, 1012.6, 47.0)) if baro else None
    hw = SimpleNamespace(cfg=cfg, cells=[_Cell(raw)], calibration=Calibration(tmp_path / "calibration.json"),
                         _GPIO=_GPIO(1 if pressed else 0), _baro=baro_dev, _light=lambda: 507.0)
    hw.door_open = lambda: not (hw._GPIO.level == 1)
    return hw


def test_tare_then_known_weight_reads_back_that_weight(tmp_path):
    hw = _hw(tmp_path, raw=10_000)
    assert sensors.tare(hw, 0) == 0
    hw.cells[0].raw = 10_000 + 500 * 420  # 500 g on the shelf, 420 counts per gram
    assert round(sensors.calibrate(hw, 0, 500), 1) == 500.0
    assert sensors.calibrated(hw, 0) == "calibrated"
    # saved where run.py reads it
    assert Calibration(tmp_path / "calibration.json").to_grams(0, 10_000 + 250 * 420) == 250


def test_the_live_view_shows_every_sensor(tmp_path):
    hw = _hw(tmp_path, pressed=False)
    text = sensors.render(hw, sensors.snapshot(hw))
    assert "Shelf 0" in text and "raw" in text and "not calibrated" in text
    assert "Door switch   OPEN" in text and "released" in text
    assert "Light         507" in text
    assert "3.8 °C" in text and "1012.6 hPa" in text and "47 % humidity" in text


def test_missing_sensors_say_how_to_fix_them(tmp_path):
    hw = _hw(tmp_path, raw=None, baro=False)
    hw._light = lambda: None
    text = sensors.render(hw, sensors.snapshot(hw))
    assert "check the HX711 wiring" in text
    assert "do_i2c" in text and "not found" in text
