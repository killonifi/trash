"""
opto_feedback.py
~~~~~~~~~~~~~~~~
Модуль для расчёта элементов оптронной обратной связи (TL431 + оптопара)
в изолированных импульсных источниках питания.

Теперь учитываются _все_ элементы обвязки:
* **R_pullup** — резистор на коллекторе/стоке фототранзистора,
* **R_LED** — токозадающий резистор светодиода оптопары,
* **R_bias** — дополнительный путь смещения TL431 (обеспечивает I_K при отсутствии тока через LED),
* **RC-сеть** между катодом и Ref TL431 (R_c, C_c, C_roll) — компенсатор Type‑II.

---------------
Быстрый старт
---------------
>>> import opto_feedback as ofb
>>> p = ofb.InputParams(v_out=12, f_sw=100e3)  # остальное по умолчанию
>>> rpt = ofb.compute_optocoupler(p)
>>> for k, v in rpt.items():
...     print(f"{k:24}: {v}")

Все величины возвращаются СИ‑единицах.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from math import pi

__all__ = ["InputParams", "compute_optocoupler"]

# ---------------------------------------------------------------------------
# 1. Входные параметры
# ---------------------------------------------------------------------------

@dataclass
class InputParams:
    """Исходные данные для расчёта оптронной ОС.

    *Поля, которые проектировщику обычно приходится менять подчёркнуты.*
    Все напряжения — в В, токи — в А, сопротивления — в Ω, частоты — в Гц.
    """

    # --- Первичная сторона --------------------------------------------------
    fb_pullup_voltage: float = 5.0       # Vcc, питающая R_pullup
    fb_voltage_min: float = 2.5          # Низкий порог входа FB контроллера
    fb_voltage_max: float = 4.5          # Высокий порог FB (макс. скважность)
    fb_pullup_resistor: float | None = None  # *Если None, рассчитывается*

    # --- Оптопара -----------------------------------------------------------
    ctr_min: float = 0.35                # *Минимальный CTR (коэф. передач)*
    led_forward_voltage_max: float = 1.30  # V_F LED при треб. токе
    c_e: float = 20e-12                  # Выходная ёмкость фототранзистора

    # --- Вторичная сторона --------------------------------------------------
    v_out: float = 12.0                  # *Номинал выходного напряжения*
    v_out_min: float | None = None       # Минимальное V_out для худ. случая

    tl431_ref: float = 2.495             # Опорное напряжение TL431
    i_k_min: float = 2e-3                # *Ток катода TL431 при регулировании*
    bias_current: float = 1e-3           # *Ток смещения через R_bias*

    # --- Частотная часть ----------------------------------------------------
    f_sw: float | None = None            # Частота переключения (если нужна)
    phase_margin_target: float = 50.0    # Треб. запас фазы, град

    # --- Допуски ------------------------------------------------------------
    led_current_margin: float = 0.10     # Запас (+10 %) к I_LED

    def __post_init__(self):
        if self.v_out_min is None:
            self.v_out_min = self.v_out

# ---------------------------------------------------------------------------
# 2. Расчёт вспомогательных величин
# ---------------------------------------------------------------------------

def calc_ipd_range(p: InputParams) -> tuple[float, float]:
    """Возвращает (I_PD_min, I_PD_max) — диапазон тока фототранзистора."""
    # Если R_pullup не задан, подберём так, чтобы I_PD_max ≈ 2 мА (эмпирически)
    if p.fb_pullup_resistor is None:
        p.fb_pullup_resistor = (p.fb_pullup_voltage - p.fb_voltage_min) / 0.002

    i_pd_min = (p.fb_pullup_voltage - p.fb_voltage_max) / p.fb_pullup_resistor
    i_pd_max = (p.fb_pullup_voltage - p.fb_voltage_min) / p.fb_pullup_resistor
    return i_pd_min, i_pd_max


def calc_iled(p: InputParams, i_pd_max: float) -> float:
    """Ток LED с учётом худшего CTR и запаса."""
    return i_pd_max / p.ctr_min * (1 + p.led_current_margin)


def calc_rled(p: InputParams, i_led: float) -> float:
    """Резистор в цепи LED (R_LED)."""
    r_led = (p.v_out_min - p.tl431_ref - p.led_forward_voltage_max) / i_led
    if r_led <= 0:
        raise ValueError(
            "Недостаток напряжения для LED + TL431. Увеличьте Vout или снизьте I_LED.")
    return r_led


def calc_rbias(p: InputParams) -> float:
    """Резистор смещения TL431 (R_bias), обеспечивающий bias_current."""
    return (p.v_out_min - p.tl431_ref) / p.bias_current


def calc_divider(p: InputParams) -> tuple[float, float]:
    """Делитель TL431: возвращает (R_upper, R_lower)."""
    r_lower = p.tl431_ref / p.i_k_min
    r_upper = (p.v_out - p.tl431_ref) / p.i_k_min
    return r_upper, r_lower


def calc_opto_poles(p: InputParams) -> dict[str, float]:
    """Полюса, связанные с оптопарой и TL431."""
    f_p_opto = 1 / (2 * pi * p.fb_pullup_resistor * p.c_e)
    f_p_tl431 = 7e3 * (p.i_k_min / 5e-3) ** 0.5
    return {"f_p_opto": f_p_opto, "f_p_tl431": f_p_tl431}


def synthesize_comp(p: InputParams, poles: dict[str, float]) -> dict[str, float]:
    """Type‑II compensator (R_c || C_c + C_roll) синтез по правилам ТI TND‑381."""
    f_z = min(poles.values())  # Нуль ставим на низший полюс
    # Частота перехода: 0.05*Fsw либо 2*макс(полюсов), если Fsw не задан
    f_c = 0.05 * p.f_sw if p.f_sw else 2 * max(poles.values())

    c_c = 10e-9                         # инженерное предположение 10 нФ
    r_c = 1 / (2 * pi * c_c * f_z)      # чтобы нуль = f_z
    f_p_roll = 5 * f_c                  # полюс свёртки выше fc ×5
    c_roll = 1 / (2 * pi * r_c * f_p_roll)

    return {
        "R_c": r_c,
        "C_c": c_c,
        "C_roll": c_roll,
        "f_zero": f_z,
        "f_p_roll": f_p_roll,
        "f_crossover_est": f_c,
    }

# ---------------------------------------------------------------------------
# 3. Точка входа
# ---------------------------------------------------------------------------

def compute_optocoupler(p: InputParams) -> dict[str, float]:
    """Полный расчёт, возвращает отчёт‑словарь."""
    i_pd_min, i_pd_max = calc_ipd_range(p)
    i_led = calc_iled(p, i_pd_max)
    r_led = calc_rled(p, i_led)
    r_bias = calc_rbias(p)
    r_upper, r_lower = calc_divider(p)
    poles = calc_opto_poles(p)
    comp = synthesize_comp(p, poles)

    report = {
        **asdict(p),
        "i_pd_min": i_pd_min,
        "i_pd_max": i_pd_max,
        "i_led": i_led,
        "R_pullup": p.fb_pullup_resistor,
        "R_LED": r_led,
        "R_bias": r_bias,
        "R_TL431_upper": r_upper,
        "R_TL431_lower": r_lower,
        **poles,
        **comp,
    }
    return report
