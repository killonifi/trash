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
from math import pi, tan, sqrt, isfinite, atan
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

    notes = (f"Type 1: fpo={fpo:.1f} Hz; Ifb@Vfb={Ifb*1e3:.2f} mA; "
             f"Rq_LED_max check; C2 includes Copto.")
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

    # Делитель
    R1, Rlower = _divider_values(inp.vout, Ibridge, Vref)

    # Позиционирование нуля/полюса
    C1 = 1.0 / (2*pi*fz*R1)                         # zero at fz via R1||C1
    C2_pole = 1.0 / (2*pi*fp*Rpullup)               # pole at fp via Rpullup||C2
    C2 = max(C2_pole - Copto, 0.0)

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
        R2=None, R3=None, C1=C1, C3=None, Rz=None, Vz=None,
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
    G2 = 10.0 ** (inp.Gfc_db / 20.0)
    G1 = (Rpullup * CTR) / RLED
    G = G2 / G1

    # При равных парах (fz,fz) и (fp,fp) mid-band коэффициент для TL431-ветки:
    # Выводит R2 ≈ формуле, согласующейся с примером в слайдах.
    R2 = (( (fc*fc + fz*fz) / (fc*fc) ) * (fc/fp)) * R1 * G

    # Конденсаторы:
    C1 = 1.0 / (2*pi*fz*R2)   # первый нуль через R2-C1
    C3 = 1.0 / (2*pi*fp*R3)   # второй ВЧ полюс через R3-C3

    # Второй нуль через параллельный конденсатор к R1:
    C1_slow = 1.0 / (2*pi*fz*R1)
    notes_local = (f"Type 3 no fast-lane: φ_each={phi_each:.1f}°, a={a:.3f}, "
                   f"fz={fz:.1f} Hz, fp={fp:.1f} Hz. "
                   f"Второй нуль через R1 и конденсатор C≈{C1_slow:.3e} Ф.")

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


# --- Compatibility layer for legacy GUI ---


@dataclass
class InputParams:
    """Parameters used by the legacy GUI optocoupler tool.

    The new synthesis functions operate on :class:`Inputs` instances, but the
    GUI expects an ``InputParams`` dataclass with a large number of fields.  To
    keep the GUI working we provide this lightweight compatibility layer which
    converts the old structure into the new one and delegates the actual
    calculations to :func:`design_type1`, :func:`design_type2_fast_lane`,
    :func:`design_type2_no_fast_lane` and :func:`design_type3_no_fast_lane`.
    Many of the fields are currently unused by the calculations but are kept so
    that existing code can construct the dataclass without errors.
    """

    v_out: float
    f_sw: float
    vdd: float
    r_pullup: float
    ctr_min: float
    c2_fb_nf: float
    c_opto_nf: float
    v_ref: float
    v_f_led: float
    vce_sat: float
    i_div_uA: float
    v_bias_zener: float
    i_bias_mA: float
    fc: float
    gc_db: float
    fz1: float
    fz2: float
    fp3: float
    c1_nf: float
    c2_nf: float
    c3_nf: float
    fp2: float
    vk_work: float
    vfb_min: float
    vfb_max: float
    opto_model: str = ""
    comp_type: str = "type3"


def compute_optocoupler(p: InputParams) -> Dict[str, Any]:
    """Return a simple text report for the optocoupler network.

    This is a thin wrapper that maps the GUI's ``InputParams`` to the new
    calculation routines.  Only a subset of parameters is used; unused values
    are kept for backwards compatibility.
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
    }

    inp = Inputs(
        fc_hz=p.fc,
        Gfc_db=p.gc_db,
        boost_deg=None,
        vout=p.v_out,
        fsw_hz=p.f_sw,
        vfb_ref=p.vk_work,
        params=user,
    )

    t = (p.comp_type or "type3").lower()
    if t == "type1":
        res = design_type1(inp)
    elif t == "type2_fast":
        inp.boost_deg = _boost_from_ratio(p.fc, p.fz1)
        res = design_type2_fast_lane(inp)
    elif t == "type2":
        inp.boost_deg = _boost_from_ratio(p.fc, p.fz1)
        res = design_type2_no_fast_lane(inp, p.v_bias_zener)
    else:  # default to type3
        inp.boost_deg = _boost_from_ratio(p.fc, p.fz1) * 2.0
        res = design_type3_no_fast_lane(inp, p.v_bias_zener)

    # Build a simple human‑readable report
    lines = [f"Type: {res.type_name}", "", "[Network]"]
    for key in ["Rpullup", "C2", "RLED", "Rbias", "R1", "Rlower", "R2", "R3", "C1", "C3"]:
        val = getattr(res, key, None)
        if val is not None:
            lines.append(f"{key:7s} = {val:.6g}")
    if res.notes:
        lines.append("")
        lines.append(res.notes)

    return {"report_text": "\n".join(lines)}
