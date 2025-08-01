import random, json, sys
sys.path.append('.')
from flyback_all_v5_patchgui_20250731_185811.flyback_design_v5 import run

def rand_outs(n):
    lst=[]
    for _ in range(n):
        v=random.uniform(3,24)
        i=random.uniform(0.2,3)
        lst.append({"name":f"out{_}","v":"%.2f"%v,"i":"%.2f"%i})
    return lst

configs=[
    (85,265,3),(36,75,2),(250,450,4),(85,115,2),(9,18,3),
    (20,60,3),(300,400,2),(48,57,4),(90,140,3),(120,240,2)
]

for idx,(vmin,vmax,n) in enumerate(configs,1):
    cfg={
        "input":{"vin_min":str(vmin),"vin_max":str(vmax),"fsw":"100k","duty_max":"0.4","eff":"0.9","input_type":"dc","f_line":"50","overload":"1.2","main_output":"out0"},
        "outputs":rand_outs(n),
        "core":{"ae_mm2":"60","le_mm":"55","bmax_T":"0.2","core_volume_mm3":"3200"},
        "geometry":{"jmax_A_per_mm2":"4","mlt_pri_mm":"40","mlt_sec_default_mm":"40","window_area_mm2":"80","copper_temp_C":"60","ac_factor_pri":"1.5","ac_factor_sec":"1.5"}
    }
    res=run(cfg)
    assert res['initial']['ipk_A']>0
print('ok')
