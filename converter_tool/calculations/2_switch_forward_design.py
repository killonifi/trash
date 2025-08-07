class TwoSwitchForwardDesign(ConverterDesign, _CoreUtils):
    """One‑quadrant two‑switch forward converter (Fig. 13.5). Energy is
    transferred while both switches are ON; flux resets through the two diodes
    when they turn OFF, eliminating the need for a separate reset winding and
    clamping MOSFET voltage to Vin.
    """
    name = "two_switch_forward"

    def calculate(self) -> Dict[str, Any]:
        p = self.params
        if p['Vin_min'] > p['Vin_max']:
            raise ValueError("Vin_min must not exceed Vin_max")

        d_max = p.get('D_max', 0.48)  # may approach 0.5, still need reset time
        n_ps = (p['Vin_min'] * d_max) / p['Vout']  # identical to single forward
        w1 = self._primary_turns(p['Vin_min'], d_max, p['B_max'],
                                 p['core_Ae'], p['f_sw'])
        w2 = math.ceil(w1 / n_ps)

        # Each MOSFET sees only bus voltage Vin
        vds = p['Vin_max']

        # Output inductor – same approach as single forward
        l_min = (p['Vout'] * (1 - d_max)) / (p['delta_I'] * p['f_sw'] * 2)
        mode = 'CCM' if self._ccm_inductor(l_min, p['Iout'], p['delta_I'],
                                           p['f_sw']) == 0 else 'DCM'

        ss0_min = self._core_ss0_min(p['Pout'], p['f_sw'], p['B_max'])

        self.results.update({
            'turns_ratio': round(n_ps, 3),
            'primary_turns': w1,
            'secondary_turns': w2,
            'vds_max': vds,
            'l_out_min_uH': round(l_min * 1e6, 2),
            'output_current_mode': mode,
            'SS0_min_cm4': round(ss0_min, 3),
        })
        return self.results