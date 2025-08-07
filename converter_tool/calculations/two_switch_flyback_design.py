# two_switch_flyback_design.py
#
# Расчёт двухключевого flyback-преобразователя (DCM/CCM)
# Автор: OpenAI o3 — адаптировано для проекта killonifi/trash
# Совместимо с ConverterDesign интерфейсом (см. base.py)

from dataclasses import dataclass, asdict
from math import sqrt

@dataclass
class TwoSwitchFlybackDesign:
    # --- входные данные ---
    V_in_min: float = 90.0     # минимальное входное, В
    V_in_max: float = 265.0    # максимальное входное, В
    V_out: float = 24.0        # выходное, В (один канал)
    P_out: float = 150.0       # мощность, Вт
    f_sw: float = 100e3        # частота, Гц
    D_max: float = 0.45        # максимально допустимый коэффициент заполнения (<0.5)
    eta: float = 0.9           # ожидаемый КПД
    V_diode: float = 0.7       # прямое падение на выходном диоде, В
    ripple_pct: float = 40.0   # относительный пульс тока ΔI/I_mean для CCM-варианта, %

    # --- расчётные результаты (заполняются в calculate) ---
    n: float = None          # передаточное отношение Np/Ns
    L_p: float = None        # индуктивность первички, Гн
    I_pk: float = None       # пиковый ток первички, А
    I_rms: float = None      # RMS ток первички, А
    V_DS_max: float = None   # макс. напряжение на MOSFET, В
    V_P: float = None        # пик напряжения на CS-конденсаторах, В
    core_mag_flux: float = None  # ΔB, Тл (для подбора сердечника)

    # -------------------------------------------------------
    def calculate(self):
        # 1. Передаточное отношение n  (Eq-1 CCM:  V_o = (D/(1-D)) * V_in / n )
        #    Рассчитываем по Vin_min и D_max — типовой worst-case для удержания D<0.5.
        self.n = (self.V_in_min * self.D_max) / (self.V_out + self.V_diode)

        # 2. Максимальный коэффициент заполнения в режиме DCM
        #    D_DCM = sqrt( P_out / (0.5 * η * V_in_min * I_pk * f_sw) ) — будет уточнён позднее

        # 3. Выбираем предельный пиковый ток так,
        #    чтобы энергия в Lp за период равнялась требуемой средней мощности (Eq-2,3,4).
        #    E_cycle = 0.5 * Lp * I_pk^2 ;   P_out = η * E_cycle * f_sw
        #    => I_pk = sqrt( 2 * P_out / (η * L_p * f_sw) )
        #    Перебор: зададим желаемую плотность тока ≈ 4 A на ватт_кельна — для стартовой оценки.
        I_pk_guess = (2 * self.P_out) / (self.V_in_min * self.D_max)  # простая оценка

        # 4. Индуктивность Lp из условия P_out  (DCM-энергетическая передача)
        self.L_p = (2 * self.P_out) / (self.eta * (I_pk_guess ** 2) * self.f_sw)

        # 5. Уточнённый пик-ток
        self.I_pk = sqrt(2 * self.P_out / (self.eta * self.L_p * self.f_sw))

        # 6. RMS-ток (треугольный ток, duty ≈ D_max)
        self.I_rms = self.I_pk * sqrt(self.D_max / 3)

        # 7. Пиковое напряжение на конденсаторе CS (Eq-13)
        self.V_P = (self.V_in_max / 2) + (self.n * (self.V_out + self.V_diode) / 2)

        # 8. Напряжение MOSFET-ов (Eq-14 + небольшой запас)
        self.V_DS_max = self.V_in_max + 0.1 * self.V_in_max  # Vin +10 %

        # 9. Плотность магнитного потока ΔB для выбора сердечника
        #    ΔB ≈ V_in_min * D_max / (N_p * A_core * f_sw) ; здесь N_p будет подобран позже,
        #    поэтому сохраните удельную величину (В * с/виток) — удобно для GUI.
        self.core_mag_flux = self.V_in_min * self.D_max / self.f_sw

        return asdict(self)

    # Короткое представление для GUI
    def summary(self):
        return {
            "n (Np/Ns)": round(self.n, 3),
            "Lp [mH]": round(self.L_p * 1e3, 3),
            "Ipk [A]": round(self.I_pk, 3),
            "Irms [A]": round(self.I_rms, 3),
            "V_DS(max) [V]": round(self.V_DS_max, 1),
            "V_P [V]": round(self.V_P, 1),
        }

# --- при автономном запуске выводим пример ---
if __name__ == "__main__":
    des = TwoSwitchFlybackDesign(
        V_in_min=90,   # В
        V_in_max=265,  # В
        V_out=24,      # В
        P_out=150,     # Вт
        f_sw=100e3     # 100 кГц
    )
    des.calculate()
    for k, v in des.summary().items():
        print(f"{k:15}: {v}")
