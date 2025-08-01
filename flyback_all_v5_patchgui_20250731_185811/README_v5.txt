Flyback Design Tool v5 (DCM)

Входные параметры (Inputs)
--------------------------
Vin_min, Vin_max [V]        — диапазон входного напряжения.
fsw [Hz]                    — частота переключения.
Dmax                        — ограничение на D(Vin_min); для оптимизатора K — верхняя граница/выбранное значение.
eff                         — целевая КПД в первом приближении (участвует в Lm).
input_type {dc|ac}          — тип входа; для ac Cin оценивается по 2·f_line.
f_line [Hz]                 — частота сети.
overload                    — коэффициент перегрузки по мощности.
main_output                 — имя основной вторички (по ней задаётся K).
cin_vrip [Vpp]              — допустимая пульсация входного конденсатора.

Outputs (многовыходные)
------------------------
name                        — имя.
Vout [V], Iout [A]          — напряжение/ток.
Ripple Vpp [V]              — допустимая пульсация.
Diode Vf [V]                — падение на диоде.
MLT sec [mm]                — средняя длина витка вторички.
Qrr [nC]                    — заряд обратного восстановления (опционально).

Core / Geometry
---------------
Ae [мм^2], le [мм], Bmax [T], Core volume [мм^3], AL [нГн/вит^2], Window [мм^2]
MLT pri/sec [мм], Jmax [A/мм^2], T_cu [°C], AC factors (pri/sec)

Ключевые формулы
----------------
(1) Vref = (D_min/(1-D_min)) · Vin_min
(2) K = Np/Ns_main = Vref / (Vout_main + Vf_main)
(3) D(Vin) = Vref / (Vin + Vref)
(4) Lm_target = Vin_min^2 · D(Vin_min)^2 · η / (2 · P_out(max) · f_sw)
(5) I_pk = Vin_min · D(Vin_min) / (Lm_target · f_sw)
(6) V_DS(ideal,max) = Vin_max + K · (Vout_main + Vf_main)
(7) VRRM_sec = (Np/Ns) · Vin_max + Vout + Vf
(8) Cout_min ≈ I_out · (1-D) / (ΔV · f_sw)
    Cin_min (DC) ≈ I_in · D / (ΔV_in · f_sw),   I_in ≈ P_out / (η · Vin_min)
(9) ΔB ≈ Vin_max · D / (N_p · Ae · f_sw)  →  N_p(min) из Bmax
(10) g ≈ μ0 · N_p^2 · Ae / Lm_target
(11) R_dc = ρ(T) · l / A,  P_cu = I_rms^2 · R_dc · k_ac
(12) Стейнмец: P_v = k · f^α · B^β,  P_core = P_v · V_core
(13) MOSFET: P_cond, P_sw ≈ 0.5·VDS·Ipk·(tr+tf)·fs·k_sw, P_Coss ≈ 0.5·Coss·VDS^2·fs, P_gate = Qg·Vg·fs
(14) Диод: P_cond ≈ I_out·Vf;  P_rr ≈ Q_rr·V_rev·f_sw

Оптимизация K (Np/Ns)
---------------------
Сканируется D(Vin_min) ∈ [dmin..dmax] с шагом dstep. Для каждого D:
  Vref(d) по (1), далее K(d) по (2). Выполняется «Этап 2» и считаются метрики:
  min_vds, min_ipk, min_vrrm, min_loss. Лучший вариант можно применить из GUI.

Выходные данные
---------------
Этап 1: Pout_total, Lm_target, Ipk, Irms, D(Vin_min/max), K, Vref, VDS_ideal, Cin_min, Cout_min[выход].
Этап 2: Np, Ns[выход], K_actual, g, Lm_actual, Ipk, Irms, t_off, DCM_ok, провода/skin, fill-factor,
        VRRM[выход], VDS (ideal/with clamp), потери по статьям, оценка η.
