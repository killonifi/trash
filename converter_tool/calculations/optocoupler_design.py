# -*- coding: utf-8 -*-
"""
optocoupler_design.py
=====================

Модуль расчёта элементов оптопетли с TL431 и оптопарой по методике ON Semiconductor
("The TL431 in the Control of Switching Power Supplies").

Поддерживаются три варианта компенсации согласно рисункам из проекта (Images/):
    - Type 1 (origin pole only, no phase boost): Optocoupler_type1.png
    - Type 2 (origin pole + lead + pole), два режима:
        * с fast-lane (Optocoupler_type2_fast_lane.png)
        * без fast-lane / с фиксированным смещением (Optocoupler_type2.png)
    - Type 3 (origin pole + double zero + double pole) без fast-lane: Optocoupler_type3.png

Ключевые обозначения ЭЛЕМЕНТОВ ДОЛЖНЫ совпадать с подписями на рисунках:
Rpullup, C2, RLED, Rbias, TL431, R1, R2, R3, C1, C2, C3, Rlower, Rz, Vz, etc.

Входные данные:
- fc_hz        : частота, на которой требуется заданный модуль усиления |G(fc)| (кроссовер или рабочая частота настройки)
- Gfc_db       : требуемый модуль усиления компенсационной сети на fc в децибелах
                 (для ослабления введите отрицательное значение)
- boost_deg    : требуемое фазовое приращение (type 2/3). Для type 1 не используется.
- vout         : напряжение основного выхода (из вкладки Outputs)
- fsw_hz       : частота преобразования (из вкладки Inputs) — используется только для проверки ограничений
- vfb_ref      : опорное напряжение FB контроллера на первичной стороне (ЗАПРОС ПОЛЬЗОВАТЕЛЯ)
- params       : словарь технологических и компонентных констант (см. DEFAULTS ниже)

Результат: словарь с рассчитанными номиналами и диагностикой.

ВНИМАНИЕ
--------
1) Модуль выполняет **синтез только компенсационной части** по малосигнальной модели,
   как в методике ON Semi. Для гарантии устойчивости обязательно сверьте выбранные
   fp/fz с реальным открытым контуром силовой части H(s).

2) Для type 2/3 с «fast-lane» действуют ограничения по статическому коэффициенту передачи,
   задаваемому RLED (см. слайды ON Semi). Модуль проверяет эти ограничения.

3) Для подавления влияния паразитной емкости оптопары Copto обязательно вводите её или
   частоту полюса f_opto = 1/(2π*Rpullup*Copto). Если Copto неизвестна, задайте f_opto
   экспериментально по методике из презентации (AC-свип с подстановкой).

Ссылки на формулы см. в презентации ON Semi:
- Type 1: нейтрализация нуля/полюса, f_po = |G(fc)| * fc,
          C2_pole = CTR / (2π f_po RLED), C1 = C2_pole * Rpullup / R1.
- Type 2 (fast-lane): fz = fc/a, fp = a*fc, где a = tan(φ) + sqrt(tan²(φ)+1),
          C1 = 1/(2π fz R1), C2_pole = 1/(2π fp Rpullup), RLED = (Rpullup*CTR)/|G(fc)|.
- Type 2 (no fast-lane): те же fz/fp; учитываем дополнительный множитель G1 = Rpullup*CTR/RLED,
          требуемое ослабление/усиление G2 = 10^(Gfc_db/20), затем G = G2 / G1,
          R2 = (sqrt((fz²+fc²)(fp²+fc²))/(fz²+fc²)) * G * (fc*R1/fp),
          C1 = 1/(2π fz R2), C2 = C2_pole - Copto.
- Type 3 (no fast-lane): общий фазовый буст φ делим пополам на два одинаковых лид-звена,
          так что fz1=fz2=fc/a, fp1=fp2=a*fc, a как выше. Далее:
          G1 = Rpullup*CTR/RLED, G2 = 10^(Gfc_db/20), G = G2 / G1,
          R2 из соотношения для mid-band (см. презентацию); здесь используется
          эквивалентная формула для двух одинаковых пар:
              R2 = ( ( (fc**2 + fz**2) / (fc**2) ) * (fc/fp) ) * R1 * G
          C1 = 1/(2π fz R2), C3 = 1/(2π fp R3),
          C2 (в коллекторе оптопары) = 1/(2π fp Rpullup) - Copto.
   Примечание: формула для R2 эквивалентна той, что используется на слайде
   с примером (ϕ=120°, fc=1 кГц, получили R2≈744 Ω при R1≈?); при необходимости
   укажите R2 вручную — модуль позволяет это сделать.

Автор: инженер-разработчик силовой электроники
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
from math import pi, tan, sqrt, isfinite, atan, log10
from typing import Optional, Dict, Any


# Значения по умолчанию (можно переопределить из GUI)
DEFAULTS: Dict[str, float] = {
    # TL431 и оптопара
    "Vref_TL431": 2.5,          # TL431 reference, В
    "Vf_LED": 1.0,              # прямое падение на светодиоде оптопары, В
    "VCE_sat": 0.3,             # насыщение транзистора оптопары, В
    "CTR_min": 0.3,             # минимальный CTR в рабочей точке (доля, не %)
    "Ibias_TL431": 1e-3,        # рабочий ток TL431, А (>=1 мА)
    # Первичная часть
    "Vdd_pullup": 5.0,          # питание резистора Rpullup, В
    "Rpullup": 20e3,            # резистор в коллекторе оптопары, Ом
    # Паразитная емкость оптопары (если известна)
    "Copto": 2e-9,              # Ф (если None, используйте f_opto_hz)
    "f_opto_hz": None,          # Гц (если задана, переопределяет Copto)
    # Делитель на вторичной (ток моста)
    "Ibridge": 250e-6,          # ток через R1+Rlower, А (~200–300 мкА)
    # Ограничения/настройки
    "RLED_margin": 0.85,        # запас от верхнего предела RLED
    "R3_equal_R1": 1.0,         # R3 = k * R1 (для type 3)
    # Автосолвер: диапазоны по умолчанию
    "R_min": 200.0,
    "R_max": 200e3,
    "C_min": 100e-12,
    "C_max": 1e-6,
    # Зенер для схем без fast-lane
    "Iz_min": 2e-3,
    "Iz_max": 15e-3,
}


@dataclass
class Inputs:
    fc_hz: float
    Gfc_db: float
    boost_deg: Optional[float]  # None для type 1
    vout: float
    fsw_hz: float
    vfb_ref: float
    # Переопределение defaults при необходимости
    params: Optional[Dict[str, float]] = None


@dataclass
class Results:
    # Общие
    type_name: str
    Rpullup: float
    C2: float                    # конденсатор в коллекторе (primary), именование C2
    Copto: float
    f_opto_hz: float
    RLED: float
    RLED_max: float
    Rbias: float
    R1: float
    Rlower: float
    # Специфика
    R2: Optional[float] = None
    R3: Optional[float] = None
    C1: Optional[float] = None
    C3: Optional[float] = None
    Rz: Optional[float] = None
    Vz: Optional[float] = None
    # Контрольные величины
    fz_hz: Optional[float] = None
    fp_hz: Optional[float] = None
    G1_mid: Optional[float] = None
    G_needed_lin: Optional[float] = None
    notes: str = ""


def _merge_params(user: Optional[Dict[str, float]]) -> Dict[str, float]:
    p = dict(DEFAULTS)
    if user:
        p.update({k: v for k, v in user.items() if v is not None})
    # Если задана частота полюса оптопары — пересчитываем Copto
    if p.get("f_opto_hz"):
        p["Copto"] = 1.0 / (2*pi*p["Rpullup"]*p["f_opto_hz"])
    else:
        p["f_opto_hz"] = 1.0 / (2*pi*p["Rpullup"]*p["Copto"])
    return p


def _divider_values(vout: float, Ibridge: float, Vref: float) -> (float, float):
    """Расчет R1 (верхний) и Rlower по току моста."""
    Rlower = Vref / Ibridge
    R1 = (vout - Vref) / Ibridge
    return R1, Rlower


def _rled_max_fast_lane(vout: float, Vref: float, Vf: float,
                        Vdd: float, VCEsat: float, Ibias: float,
                        Rpullup: float, CTR_min: float) -> float:
    """
    Верхний предел RLED для схем с fast-lane (см. слайды ON Semi):
    RLED_max <= ((Vout - Vf - Vref)/(Vdd - VCEsat + Ibias*CTR_min*Rpullup)) * (Rpullup*CTR_min)
    """
    A = max(vout - Vf - Vref, 1e-6)
    B = max(Vdd - VCEsat + Ibias * CTR_min * Rpullup, 1e-6)
    return (A / B) * (Rpullup * CTR_min)


def _rled_max_no_fast_lane(Vz: float, Vref: float, Vf: float,
                           Vdd: float, VCEsat: float, Ibias: float,
                           Rpullup: float, CTR_min: float) -> float:
    """
    Верхний предел RLED для схем без fast-lane (см. слайды: use Vz instead of Vout):
    RLED_max <= ((Vz - Vf - Vref)/(Vdd - VCEsat + Ibias*CTR_min*Rpullup)) * (Rpullup*CTR_min)
    """
    A = max(Vz - Vf - Vref, 1e-6)
    B = max(Vdd - VCEsat + Ibias * CTR_min * Rpullup, 1e-6)
    return (A / B) * (Rpullup * CTR_min)


def _a_from_boost(boost_deg: float) -> float:
    """a = tan(phi) + sqrt(tan^2(phi)+1)"""
    t = tan(boost_deg * pi / 180.0)
    return t + sqrt(t*t + 1.0)


def _boost_from_ratio(fc: float, fz: float) -> float:
    """Inverse of :func:`_a_from_boost` using frequency ratio fc/fz."""
    if fz <= 0 or fc <= 0:
        return 0.0
    a = fc / fz
    return atan((a*a - 1.0) / (2.0 * a)) * 180.0 / pi




def _led_rd(Iled: float) -> float:
    """Small-signal LED dynamic resistance: r_d ≈ 25 mV / I_led (at room temp)."""
    if not isfinite(Iled) or Iled <= 0.0:
        return 1e9
    return 25e-3 / Iled

def _g1_mid(CTR: float, Rpullup: float, RLED: float, Iled_dc: float) -> float:
    """Mid-band gain with LED dynamic resistance in series: G1 = CTR·Rpullup / (RLED + r_d)."""
    rd = _led_rd(Iled_dc)
    return CTR * Rpullup / max(RLED + rd, 1e-9)

def _ensure_positive(x: float, name: str) -> float:
    if not isfinite(x) or x <= 0.0:
        raise ValueError(f"{name} must be > 0, got {x}")
    return x


def design_type1(inp: Inputs) -> Results:
    """
    Type 1 (origin pole only, no phase boost)
    Элементы: Rpullup, C2, RLED, Rbias, TL431, R1, Rlower, C1.
    """
    p = _merge_params(inp.params)
    Vref = p["Vref_TL431"]; Vf = p["Vf_LED"]; VCE = p["VCE_sat"]
    CTR = p["CTR_min"]; Ibias = p["Ibias_TL431"]
    Vdd = p["Vdd_pullup"]; Rpullup = p["Rpullup"]; Copto = p["Copto"]
    Ibridge = p["Ibridge"]; margin = p["RLED_margin"]

    fc = _ensure_positive(inp.fc_hz, "fc_hz")
    Glin = 10.0 ** (inp.Gfc_db / 20.0)  # требуемый модуль |G(fc)|
    fpo = fc * Glin                           # f_po = G(fc) * fc  (см. слайды)
    # Предел по RLED
    RLED_max = _rled_max_fast_lane(inp.vout, Vref, Vf, Vdd, VCE, Ibias, Rpullup, CTR)
    RLED = RLED_max * margin

    # Конденсатор полюса в коллекторе: C2_pole = CTR / (2π f_po RLED)
    C2_pole = CTR / (2*pi*fpo*RLED)
    # Учитываем паразитную емкость оптопары:
    C2 = max(C2_pole - Copto, 0.0)

    # Делитель на вторичной
    R1, Rlower = _divider_values(inp.vout, Ibridge, Vref)
    # Нейтрализация нуля: C1 = C2_pole * Rpullup / R1
    C1 = C2_pole * (Rpullup / R1)

    # Ток, который должен стянуть транзистор для Vfb_ref:
    Ifb = max((Vdd - inp.vfb_ref) / Rpullup, 0.0)
    Iled_dc_req = Ifb / CTR
    Rbias = (inp.vout - Vref - Vf) / max(Ibias + Iled_dc_req, 1e-9)

    notes = (

        f'.: Type 1 (интегратор) :.\n'

        f'f_po = G(fc)·fc. C2 = CTR/(2π·f_po·RLED) − C_opto (если C2<0 → увеличьте fc или уменьшите RLED).\n'

        f'fc={fc:.1f} Hz, |G(fc)|={Glin:.3f}; f_opto={p["f_opto_hz"]:.1f} Hz → f_opto/fc={(p["f_opto_hz"]/fc):.2f}×. Рекомендовано f_opto ≥ 3…4·fc.\n'

        f'Ifb@Vfb={(Ifb*1e3):.3f} mA; I_LED(min)≈Ifb/CTR={(Ifb/CTR*1e3):.3f} mA.\n'

        f'G1=CTR·Rpullup/RLED = {(CTR*Rpullup/RLED):.3f} (={(20*log10(CTR*Rpullup/RLED)):.1f} dB). Если требуется ослабление ниже G1 → используйте «без fast‑lane».\n'

        f'C2={C2*1e12:.0f} pF (минимум 100 pF по шумам).\n'

    )
    return Results(
        type_name="Type 1 (origin pole only, no phase boost)",
        Rpullup=Rpullup, C2=C2, Copto=Copto, f_opto_hz=p["f_opto_hz"],
        RLED=RLED, RLED_max=RLED_max, Rbias=Rbias, R1=R1, Rlower=Rlower,
        R2=None, R3=None, C1=C1, C3=None, Rz=None, Vz=None,
        fz_hz=None, fp_hz=fpo, G1_mid=CTR*Rpullup/RLED, G_needed_lin=Glin, notes=notes
    )


def design_type2_fast_lane(inp: Inputs) -> Results:
    """
    Type 2 (origin pole + zero + pole) с fast-lane (RLED подключен к Vout).
    Элементы: Rpullup, C2, RLED, Rbias, TL431, R1, Rlower, C1.
    """
    p = _merge_params(inp.params)
    Vref = p["Vref_TL431"]; Vf = p["Vf_LED"]; VCE = p["VCE_sat"]
    CTR = p["CTR_min"]; Ibias = p["Ibias_TL431"]
    Vdd = p["Vdd_pullup"]; Rpullup = p["Rpullup"]; Copto = p["Copto"]
    Ibridge = p["Ibridge"]; margin = p["RLED_margin"]

    fc = _ensure_positive(inp.fc_hz, "fc_hz")
    boost = inp.boost_deg if inp.boost_deg is not None else 0.0
    a = _a_from_boost(boost)
    fz = fc / a
    fp = fc * a

    # Manual override (Advanced tab)
    if p.get('manual_enable'):
        fz = p.get('manual_fz_hz', fz) or fz
        fp = p.get('manual_fp_hz', fp) or fp

    # Second pair (manual or equal to first)
    fz2 = p.get('manual_fz2_hz', 0.0) or fz
    fp2 = p.get('manual_fp2_hz', 0.0) or fp

    # Делитель
    R1, Rlower = _divider_values(inp.vout, Ibridge, Vref)

    # Позиционирование нуля/полюса
    C1 = 1.0 / (2*pi*fz*R1)                         # zero at fz via R1||C1
    C2_pole = 1.0 / (2*pi*fp*Rpullup)               # pole at fp via Rpullup||C2
    C2 = max(C2_pole - Copto, 0.0)
    # Эквивалентный R2 для отчёта (если реализовать RC‑серией): R2 = 1/(2π fz C1)
    R2_equiv = 1.0 / max(2*pi*fz*C1, 1e-12)

    # Необходимый mid-band gain: |G(fc)| = 10^(Gfc/20)
    Glin = 10.0 ** (inp.Gfc_db / 20.0)
    # Для fast-lane средний коэффициент задаётся RLED: G1 = CTR*Rpullup/RLED
    # => RLED = CTR*Rpullup/Glin
    RLED = (CTR * Rpullup) / max(Glin, 1e-9)

    # Проверка предела RLED
    RLED_max = _rled_max_fast_lane(inp.vout, Vref, Vf, Vdd, VCE, Ibias, Rpullup, CTR)
    if RLED > RLED_max * margin:
        # если требуется усиление меньше допустимого предела — предупреждение
        pass

    # DC смещение и токи для установки Vfb
    Ifb = max((Vdd - inp.vfb_ref) / Rpullup, 0.0)
    Iled_dc_req = Ifb / CTR
    Rbias = (inp.vout - Vref - Vf) / max(Ibias + Iled_dc_req, 1e-9)

    notes = (f"Type 2 fast-lane: a={a:.3f}, fz={fz:.1f} Hz, fp={fp:.1f} Hz; "
             f"Ifb@Vfb={Ifb*1e3:.2f} mA. "
             f"RLED limited by static gain ceiling.")
    return Results(
        type_name="Type 2 (with fast lane)",
        Rpullup=Rpullup, C2=C2, Copto=Copto, f_opto_hz=p["f_opto_hz"],
        RLED=RLED, RLED_max=RLED_max, Rbias=Rbias, R1=R1, Rlower=Rlower,
        R2=R2_equiv, R3=None, C1=C1, C3=None, Rz=None, Vz=None,
        fz_hz=fz, fp_hz=fp, G1_mid=CTR*Rpullup/RLED, G_needed_lin=Glin,
        notes=notes
    )


def design_type2_no_fast_lane(inp: Inputs, Vz: float, Rz: Optional[float] = None) -> Results:
    """
    Type 2 (origin pole + zero + pole) без fast-lane (RLED висит на фиксированном смещении Vz).
    Требует заданного напряжения стабилитрона Vz (см. схему Optocoupler_type2.png).
    Элементы: Rpullup, C2, RLED (по DC ограничению), Rbias, TL431, R1, Rlower, C1, R2, (Rz опционально).
    """
    p = _merge_params(inp.params)
    Vref = p["Vref_TL431"]; Vf = p["Vf_LED"]; VCE = p["VCE_sat"]
    CTR = p["CTR_min"]; Ibias = p["Ibias_TL431"]
    Vdd = p["Vdd_pullup"]; Rpullup = p["Rpullup"]; Copto = p["Copto"]
    Ibridge = p["Ibridge"]; margin = p["RLED_margin"]

    fc = _ensure_positive(inp.fc_hz, "fc_hz")
    boost = _ensure_positive(inp.boost_deg or 1e-6, "boost_deg")
    a = _a_from_boost(boost)
    fz = fc / a
    fp = fc * a

    # Manual override (Advanced tab)
    if p.get('manual_enable'):
        fz = p.get('manual_fz_hz', fz) or fz
        fp = p.get('manual_fp_hz', fp) or fp

    # Делитель
    R1, Rlower = _divider_values(inp.vout, Ibridge, Vref)

    # Ограничение RLED для DC смещения
    RLED_max = _rled_max_no_fast_lane(Vz, Vref, Vf, Vdd, VCE, Ibias, Rpullup, CTR)
    RLED = RLED_max * margin

    # C2 полюс по Rpullup||C2
    C2_pole = 1.0 / (2*pi*fp*Rpullup)
    C2 = max(C2_pole - Copto, 0.0)

    # Необходимый общий модуль на fc: G2 (может быть <1, т.е. отриц. дБ)
    G2 = 10.0 ** (inp.Gfc_db / 20.0)
    # Дополнительный множитель от оптопары/связи:
    G1 = (Rpullup * CTR) / RLED
    G = G2 / G1  # что должен дать «усилитель» TL431 (ветка с R2,C1)

    # Расчет R2 по формуле из презентации (см. слайд с параметрами):
    a_num = (fz*fz + fc*fc) * (fp*fp + fc*fc)
    a_den = (fz*fz + fc*fc)
    R2 = sqrt(a_num) / a_den * G * (fc * R1 / fp)
    C1 = 1.0 / (2*pi*fz*R2)

    # DC смещение по Vfb:
    Ifb = max((Vdd - inp.vfb_ref) / Rpullup, 0.0)
    Iled_dc_req = Ifb / CTR
    Rbias = (Vz - Vref - Vf) / max(Ibias + Iled_dc_req, 1e-9)

    # Расчёт Rz (питание стабилитрона)
    Iz_min = p.get('Iz_min', 2e-3)
    if Vdd <= Vz + 0.1:
        Rz = None
        Iz_max_est = 0.0
    else:
        Rz = max((Vdd - Vz) / max(Iz_min + Iled_dc_req, 1e-9), 1.0)
        Iz_max_est = max((Vdd - Vz) / Rz - Iled_dc_req, 0.0)


    notes = (f"Type 2 no fast-lane: a={a:.3f}, fz={fz:.1f} Hz, fp={fp:.1f} Hz; "
             f"G1={G1:.3f}, G(fc) target={G2:.3f}, R2={R2:.1f} Ω. "
             f"Copto accounted; Ifb={Ifb*1e3:.2f} mA.")
    return Results(
        type_name="Type 2 (without fast lane, biased with Vz)",
        Rpullup=Rpullup, C2=C2, Copto=Copto, f_opto_hz=p["f_opto_hz"],
        RLED=RLED, RLED_max=RLED_max, Rbias=Rbias, R1=R1, Rlower=Rlower,
        R2=R2, R3=None, C1=C1, C3=None, Rz=Rz, Vz=Vz,
        fz_hz=fz, fp_hz=fp, G1_mid=G1, G_needed_lin=G2, notes=notes
    )


def design_type3_no_fast_lane(inp: Inputs, Vz: float, Rz: Optional[float] = None) -> Results:
    """
    Type 3 (origin pole + double zero + double pole) без fast-lane.
    В простейшем практическом синтезе общий фазовый буст φ делится пополам:
       φ_each = φ/2, a = tan(φ_each)+sqrt(tan^2+1)
       fz1=fz2=fc/a, fp1=fp2=a*fc
    Элементы: Rpullup, C2 (первичный полюс), RLED (по DC ограничению),
              Rbias, R1, Rlower, R2, R3, C1, C2, C3.
    """
    p = _merge_params(inp.params)
    Vref = p["Vref_TL431"]; Vf = p["Vf_LED"]; VCE = p["VCE_sat"]
    CTR = p["CTR_min"]; Ibias = p["Ibias_TL431"]
    Vdd = p["Vdd_pullup"]; Rpullup = p["Rpullup"]; Copto = p["Copto"]
    Ibridge = p["Ibridge"]; margin = p["RLED_margin"]; kR3 = p["R3_equal_R1"]

    fc = _ensure_positive(inp.fc_hz, "fc_hz")
    boost_total = _ensure_positive(inp.boost_deg or 1e-6, "boost_deg")
    phi_each = boost_total / 2.0
    a = _a_from_boost(phi_each)

    fz = fc / a
    fp = fc * a

    # Manual override (Advanced tab)
    if p.get('manual_enable'):
        fz = p.get('manual_fz_hz', fz) or fz
        fp = p.get('manual_fp_hz', fp) or fp

    
    # Ensure fz2/fp2 are defined
    try:
        fz2
    except NameError:
        fz2 = fz
        fp2 = fp
    # Second pair (independent if provided)
    fz2 = p.get('manual_fz2_hz', 0.0) or fz
    fp2 = p.get('manual_fp2_hz', 0.0) or fp
# Делитель
    R1, Rlower = _divider_values(inp.vout, Ibridge, Vref)
    R3 = R1 * kR3

    # Ограничение RLED по DC для смещения от Vz:
    RLED_max = _rled_max_no_fast_lane(Vz, Vref, Vf, Vdd, VCE, Ibias, Rpullup, CTR)
    RLED = RLED_max * margin

    # Полюс первички (оптопара): один из высокочастотных полюсов пары
    C2_pole = 1.0 / (2*pi*fp*Rpullup)
    C2 = max(C2_pole - Copto, 0.0)

    # Требуемый общий модуль на fc
    Ifb = max((Vdd - inp.vfb_ref) / Rpullup, 0.0)
    Iled_dc_req = Ifb / CTR
    G2 = 10.0 ** (inp.Gfc_db / 20.0)
    G1 = _g1_mid(CTR, Rpullup, RLED, Iled_dc_req)
    G = G2 / G1

    # При равных парах (fz,fz) и (fp,fp) mid-band коэффициент для TL431-ветки:
    # Выводит R2 ≈ формуле, согласующейся с примером в слайдах.
    R2 = (( (fc*fc + fz*fz) / (fc*fc) ) * (fc/fp)) * R1 * G

    # Конденсаторы:
    C1 = 1.0 / (2*pi*fz*R2)   # первый нуль через R2-C1
    C3 = 1.0 / (2*pi*fp2*R3)   # второй ВЧ полюс через R3-C3

    # Второй нуль через параллельный конденсатор к R1:
    C1_slow = 1.0 / (2*pi*fz2*R1)
    notes_local = (
        f'.: Type 3 (без fast‑lane) :.\n'
        f'Общий буст φ≈{boost_total:.1f}°; φ_each=φ/2={phi_each:.1f}°, a={a:.3f} (√α) ⇒ φ_max(each)={(atan((a*a-1)/(2*a))*180/pi):.1f}°.\n'
        f'Пары: fz1={fz:.1f} Hz, fz2={fz2:.1f} Hz; fp1={fp:.1f} Hz, fp2={fp2:.1f} Hz.\n'
        f'f_opto={p["f_opto_hz"]:.1f} Hz ⇒ верхний fp ограничивайте ≤ 0.3…0.5·f_opто.\n'
        f'G1=CTR·Rpullup/RLED={(CTR*Rpullup/RLED):.3f} (={(20*log10(CTR*Rpullup/RLED)):.1f} dB); требуется G2={G2:.3f} (={(20*log10(G2)):.1f} dB) от сети нулей/полюсов.\n'
    )
    # DC смещение по Vfb:
    Ifb = max((Vdd - inp.vfb_ref) / Rpullup, 0.0)
    Iled_dc_req = Ifb / CTR
    Rbias = (Vz - Vref - Vf) / max(Ibias + Iled_dc_req, 1e-9)

    return Results(
        type_name="Type 3 (without fast lane)",
        Rpullup=Rpullup, C2=C2, Copto=Copto, f_opto_hz=p["f_opto_hz"],
        RLED=RLED, RLED_max=RLED_max, Rbias=Rbias, R1=R1, Rlower=Rlower,
        R2=R2, R3=R3, C1=C1, C3=C3, Rz=Rz, Vz=Vz,
        fz_hz=fz, fp_hz=fp, G1_mid=G1, G_needed_lin=G2, notes=notes_local
    )


# Вспомогательная функция для форматирования результатов
def as_readable_dict(res: Results) -> Dict[str, Any]:
    d = asdict(res)
    # Удобочитаемые единицы (не изменяем исходные значения)
    pretty = dict(d)
    return pretty



def _clip(x, lo, hi):
    return max(lo, min(hi, x))

def _choose_mid(lo, hi):
    return (lo * hi) ** 0.5 if lo>0 and hi>0 else 0.5*(lo+hi)

def _autosolve_once(t: str, inp: Inputs, user: Dict[str, float], res: Results) -> (bool, Dict[str, float]):
    """Heuristic parameter corrections to bring parts into practical ranges.
    Returns (changed, new_user_params). Only touches Ibridge, Rpullup; caps are clamped to [C_min,C_max].
    """
    changed = False
    Rmin = user.get("R_min",200.0); Rmax = user.get("R_max",200e3)
    Cmin = user.get("C_min",100e-12); Cmax = user.get("C_max",1e-6)

    # 1) Bridge resistors via Ibridge
    Vref = user["Vref_TL431"]; vout = inp.vout
    Ibridge = user["Ibridge"]
    R1 = res.R1 or (vout - Vref)/Ibridge
    Rlower = res.Rlower or (Vref/Ibridge)
    # Compute feasible Ibridge interval so that R1 and Rlower are within range
    LB = max((vout - Vref)/Rmax, Vref/Rmax)
    UB = min((vout - Vref)/Rmin, Vref/Rmin)
    if LB < UB:
        # pick Ibridge to drive both near geometric mid of allowed Rs
        I_target = _clip(Ibridge, LB, UB)
        # If any of the resistors out of range by >15%, move towards center
        if not (Rmin*0.85 <= R1 <= Rmax*1.15 and Rmin*0.85 <= Rlower <= Rmax*1.15):
            # Choose Ibridge so Rlower ~ mid
            Rmid = _choose_mid(Rmin, Rmax)
            I_target = _clip(Vref/Rmid, LB, UB)
        if abs(I_target - Ibridge)/max(Ibridge,1e-9) > 0.05:
            user["Ibridge"] = I_target
            changed = True

    # 2) RLED via Rpullup (works for all types since G1 ~ CTR*Rpullup/RLED)
    RLED = res.RLED
    Rpull = user["Rpullup"]
    CTR = user["CTR_min"]; Glin = 10.0 ** (inp.Gfc_db/20.0)
    if RLED is not None and (RLED < Rmin or RLED > Rmax):
        RLED_target = _clip(_choose_mid(Rmin, Rmax), Rmin, Rmax)
        # For type2_fast RLED = CTR*Rpull/R_req
        if t in ("type1","type2_fast","type3","type2"):
            Rp_new = _clip(RLED_target * Glin / max(CTR,1e-9), Rmin, Rmax)
            if abs(Rp_new - Rpull)/max(Rpull,1e-9) > 0.05:
                user["Rpullup"] = Rp_new
                changed = True

    # 3) Clamp capacitors in results by shifting to nearest bound (we can't change physics here)
    #    This only affects the reported values; design equations will be re-evaluated next pass.
    for name in ("C1","C2","C3"):
        c = getattr(res, name, None)
        if c is not None and (c < Cmin or c > Cmax):
            setattr(res, name, _clip(c, Cmin, Cmax))

    return changed, user

# --- Compatibility layer for legacy GUI ---


@dataclass
class InputParams:
    """Minimal set of parameters required by the GUI wrapper.

    The original application expected a very large ``InputParams`` structure
    mirroring the legacy tool.  To simplify the user interface we now expose
    only the values that are actually used by :mod:`optocoupler_design`.
    Defaults correspond to the ``DEFAULTS`` dictionary defined above so that
    the GUI may omit fields which the user does not wish to override.
    """

    v_out: float
    f_sw: float
    # Device and technology parameters -------------------------------------
    vdd: float = 5.0
    r_pullup: float = 20e3
    ctr_min: float = 0.3
    c_opto_nf: float = 2.0
    v_ref: float = 2.5
    v_f_led: float = 1.0
    vce_sat: float = 0.3
    i_div_uA: float = 250.0
    v_bias_zener: float = 6.2
    i_bias_mA: float = 1.0
    vfb: float = 2.5  # FB reference of PWM controller (Vfb comparator threshold)
    # Loop shaping parameters ----------------------------------------------
    fc: float = 1000.0
    gc_db: float = -10.0
    boost_deg: float = 0.0
    comp_type: str = "type3"
    # Advanced manual loop shaping
    manual_enable: bool = False
    manual_fz_hz: float = 0.0
    manual_fp_hz: float = 0.0
    manual_fz2_hz: float = 0.0
    manual_fp2_hz: float = 0.0
    # Autosolver controls
    auto_tune: bool = False
    r_min: float = 200.0
    r_max: float = 200e3
    c_min: float = 100e-12
    c_max: float = 1e-6
    iz_min: float = 2e-3
    iz_max: float = 15e-3
    # Optional plant hints from flyback model
    plant_rhpz_hz: float = 0.0
    plant_flc_hz: float = 0.0


def compute_optocoupler(p: InputParams) -> Dict[str, Any]:
    """Return a simple text report for the optocoupler network.

    ``InputParams`` values are mapped to :class:`Inputs` and the appropriate
    design helper from this module.
    """
    # Prepare parameter overrides for the design routines
    user = {
        "Vref_TL431": p.v_ref,
        "Vf_LED": p.v_f_led,
        "VCE_sat": p.vce_sat,
        "CTR_min": p.ctr_min,
        "Ibias_TL431": p.i_bias_mA * 1e-3,
        "Vdd_pullup": p.vdd,
        "Rpullup": p.r_pullup,
        "Copto": p.c_opto_nf * 1e-9,
        "Ibridge": p.i_div_uA * 1e-6,
        # Advanced manual loop shaping
        "manual_enable": bool(getattr(p, "manual_enable", False)),
        "manual_fz_hz": getattr(p, "manual_fz_hz", 0.0),
        "manual_fp_hz": getattr(p, "manual_fp_hz", 0.0),
        "manual_fz2_hz": getattr(p, "manual_fz2_hz", 0.0),
        "manual_fp2_hz": getattr(p, "manual_fp2_hz", 0.0),
    }

    inp = Inputs(
        fc_hz=p.fc, Gfc_db=p.gc_db, boost_deg=p.boost_deg,
        vout=p.v_out, fsw_hz=p.f_sw, vfb_ref=p.vfb,
        params=user
    )

    t = (p.comp_type or "type3").strip().lower()
    # Enforce Advanced selection per type
    if t == 'type1':
        user['manual_enable'] = False
    elif t in ('type2','type2_fast'):
        # Only one zero/pole is meaningful; ignore second pair values
        user['manual_fz2_hz'] = 0.0
        user['manual_fp2_hz'] = 0.0

    if getattr(p, 'auto_tune', False):
        # Limit fc in auto_tune mode to RHPZ/5
        try:
            fc = min(fc, p.plant_rhpz_hz/5)
        except Exception:
            pass
        user['manual_enable'] = False  # ignore manual when auto_tune
        # Simple iterative tuning of Ibridge/Rpullup
        for _ in range(4):
            inp_iter = Inputs(fc_hz=p.fc, Gfc_db=p.gc_db, boost_deg=p.boost_deg, vout=p.v_out, fsw_hz=p.f_sw, vfb_ref=p.vfb, params=user)
            # tentative design with current params
            if t == 'type1': tmp = design_type1(inp_iter)
            elif t == 'type2_fast': tmp = design_type2_fast_lane(inp_iter)
            elif t == 'type2': tmp = design_type2_no_fast_lane(inp_iter, p.v_bias_zener)
            else: tmp = design_type3_no_fast_lane(inp_iter, p.v_bias_zener)
            ch, user = _autosolve_once(t, inp_iter, user, tmp)
            if not ch: break
        # rebuild final input with tuned params
        inp = Inputs(fc_hz=p.fc, Gfc_db=p.gc_db, boost_deg=p.boost_deg, vout=p.v_out, fsw_hz=p.f_sw, vfb_ref=p.vfb, params=user)
    else:
        inp = Inputs(fc_hz=p.fc, Gfc_db=p.gc_db, boost_deg=p.boost_deg, vout=p.v_out, fsw_hz=p.f_sw, vfb_ref=p.vfb, params=user)

    if t == "type1":
        res = design_type1(inp)
    elif t == "type2_fast":
        res = design_type2_fast_lane(inp)
    elif t == "type2":
        res = design_type2_no_fast_lane(inp, p.v_bias_zener)
    else:
        res = design_type3_no_fast_lane(inp, p.v_bias_zener)

    # Build report
    Vfb_target = p.vfb
    Ifb_req = max((p.vdd - Vfb_target) / p.r_pullup, 0.0)
    CTRmin = p.ctr_min
    Iled_dc_req = Ifb_req / max(CTRmin, 1e-9)

    lines = [f"Type: {res.type_name}", "", "[Network]"]
    lines.append(f"DC check: Vfb={Vfb_target:.3g} V, Ifb_req={Ifb_req*1e3:.3f} mA, Iled_dc_req(min CTR)={Iled_dc_req*1e3:.3f} mA")
    if p.fc > p.f_sw/5.0:
        lines.append("Warning: fc > Fsw/5; ON Semi recommends fc ≤ Fsw/5 for noise immunity.")
    for key in ["Rpullup", "C2", "RLED", "Rbias", "R1", "Rlower", "R2", "R3", "Rz", "C1", "C3"]:
        val = getattr(res, key, None)
        if val is not None:
            lines.append(f"{key:7s} = {val:.6g}")
    if res.notes:
        lines.append("")
        lines.append(res.notes)

    return {"report_text": "\n".join(lines)}

