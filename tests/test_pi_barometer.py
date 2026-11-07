"""Checks the barometer math against the Bosch datasheets' worked examples."""
import pytest

from pi_node.barometer import (
    Bmp180Calib,
    Bmx280Calib,
    bmp180_compensate,
    bmx280_pressure_pa,
    bmx280_temperature,
)
from pi_node.hx711 import Calibration, twos_complement_24

# BMP280 datasheet, section 8.2 (float compensation example)
BMP280_EXAMPLE = Bmx280Calib(
    T1=27504, T2=26435, T3=-1000,
    P1=36477, P2=-10685, P3=3024, P4=2855, P5=140, P6=-7, P7=15500, P8=-14600, P9=6000,
)


def test_bmp280_temperature_matches_datasheet():
    temp, _ = bmx280_temperature(519888, BMP280_EXAMPLE)
    assert temp == pytest.approx(25.08, abs=0.01)


def test_bmp280_pressure_matches_datasheet():
    _, t_fine = bmx280_temperature(519888, BMP280_EXAMPLE)
    assert bmx280_pressure_pa(415148, t_fine, BMP280_EXAMPLE) == pytest.approx(100653.27, abs=0.5)


def test_bmp180_matches_datasheet():
    # BMP180 datasheet, section 3.5 worked example (oss = 0)
    calib = Bmp180Calib(AC1=408, AC2=-72, AC3=-14383, AC4=32741, AC5=32757, AC6=23153,
                        B1=6190, B2=4, MB=-32768, MC=-8711, MD=2868)
    temp, pressure = bmp180_compensate(27898, 23843, calib)
    assert temp == pytest.approx(15.0)
    assert pressure == 69964


def test_twos_complement_24():
    assert twos_complement_24(0x000001) == 1
    assert twos_complement_24(0x7FFFFF) == 8388607
    assert twos_complement_24(0xFFFFFF) == -1
    assert twos_complement_24(0x800000) == -8388608


def test_load_cell_calibration_round_trip(tmp_path):
    cal = Calibration(tmp_path / "cal.json")
    cal.tare(0, raw_empty=8000)
    cal.set_known_weight(0, raw_loaded=8000 + 210_000, known_grams=500)
    assert cal.to_grams(0, 8000) == pytest.approx(0)
    assert cal.to_grams(0, 8000 + 420_000) == pytest.approx(1000)
    # persisted and reloaded
    assert Calibration(tmp_path / "cal.json").to_grams(0, 8000 + 210_000) == pytest.approx(500)
