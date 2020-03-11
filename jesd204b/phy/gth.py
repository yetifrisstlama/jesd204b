from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from litex.soc.interconnect.csr import *
from litex.soc.cores.code_8b10b import Encoder

from jesd204b.phy.gth_init import GTHInit
from jesd204b.phy.prbs import *


class GTHChannelPLL(Module):
    def __init__(self, refclk, refclk_freq, linerate):
        self.refclk = refclk
        self.reset = Signal()
        self.lock = Signal()
        self.config = self.compute_config(refclk_freq, linerate)

    @staticmethod
    def compute_config(refclk_freq, linerate):
        for n1 in 4, 5:
            for n2 in 1, 2, 3, 4, 5:
                for m in 1, 2:
                    vco_freq = refclk_freq*(n1*n2)/m
                    if 2.0e9 <= vco_freq <= 6.25e9:
                        for d in 1, 2, 4, 8, 16:
                            current_linerate = vco_freq*2/d
                            if current_linerate == linerate:
                                return {"n1": n1, "n2": n2, "m": m, "d": d,
                                        "vco_freq": vco_freq,
                                        "clkin": refclk_freq,
                                        "linerate": linerate}
        msg = "No config found for {:3.2f} MHz refclk / {:3.2f} Gbps linerate."
        raise ValueError(msg.format(refclk_freq/1e6, linerate/1e9))

    def __repr__(self):
        r = """
GTHChannelPLL
==============
  overview:
  ---------
       +--------------------------------------------------+
       |                                                  |
       |   +-----+  +---------------------------+ +-----+ |
       |   |     |  | Phase Frequency Detector  | |     | |
CLKIN +----> /M  +-->       Charge Pump         +-> VCO +---> CLKOUT
       |   |     |  |       Loop Filter         | |     | |
       |   +-----+  +---------------------------+ +--+--+ |
       |              ^                              |    |
       |              |    +-------+    +-------+    |    |
       |              +----+  /N2  <----+  /N1  <----+    |
       |                   +-------+    +-------+         |
       +--------------------------------------------------+
                            +-------+
                   CLKOUT +->  2/D  +-> LINERATE
                            +-------+
  config:
  -------
    CLKIN    = {clkin}MHz
    CLKOUT   = CLKIN x (N1 x N2) / M = {clkin}MHz x ({n1} x {n2}) / {m}
             = {vco_freq}GHz
    LINERATE = CLKOUT x 2 / D = {vco_freq}GHz x 2 / {d}
             = {linerate}GHz
""".format(clkin=self.config["clkin"]/1e6,
           n1=self.config["n1"],
           n2=self.config["n2"],
           m=self.config["m"],
           vco_freq=self.config["vco_freq"]/1e9,
           d=self.config["d"],
           linerate=self.config["linerate"]/1e9)
        return r


class GTHQuadPLL(Module):
    def __init__(self, refclk, refclk_freq, linerate):
        self.clk = Signal()
        self.refclk = Signal()
        self.reset = Signal()
        self.lock = Signal()
        self.config = self.compute_config(refclk_freq, linerate)

        # # #

        self.specials += \
            Instance("GTHE3_COMMON",
                # common
                i_GTREFCLK00=refclk,
                i_GTREFCLK01=refclk,
                i_QPLLRSVD1=0,
                i_QPLLRSVD2=0,
                i_QPLLRSVD3=0,
                i_QPLLRSVD4=0,
                i_BGBYPASSB=1,
                i_BGMONITORENB=1,
                i_BGPDB=1,
                i_BGRCALOVRD=0b11111,
                i_BGRCALOVRDENB=0b1,
                i_RCALENB=1,

                # qpll0
                p_QPLL0_FBDIV=self.config["n"],
                p_QPLL0_REFCLK_DIV=self.config["m"],
                i_QPLL0CLKRSVD0=0,
                i_QPLL0CLKRSVD1=0,
                i_QPLL0LOCKDETCLK=ClockSignal(),
                i_QPLL0LOCKEN=1,
                o_QPLL0LOCK=self.lock if self.config["qpll"] == "qpll0" else
                            Signal(),
                o_QPLL0OUTCLK=self.clk if self.config["qpll"] == "qpll0" else
                              Signal(),
                o_QPLL0OUTREFCLK=self.refclk if self.config["qpll"] == "qpll0" else
                                 Signal(),
                i_QPLL0PD=0 if self.config["qpll"] == "qpll0" else 1,
                i_QPLL0REFCLKSEL=0b001,
                i_QPLL0RESET=self.reset,

                # qpll1
                p_QPLL1_FBDIV=self.config["n"],
                p_QPLL1_REFCLK_DIV=self.config["m"],
                i_QPLL1CLKRSVD0=0,
                i_QPLL1CLKRSVD1=0,
                i_QPLL1LOCKDETCLK=ClockSignal(),
                i_QPLL1LOCKEN=1,
                o_QPLL1LOCK=self.lock if self.config["qpll"] == "qpll1" else
                            Signal(),
                o_QPLL1OUTCLK=self.clk if self.config["qpll"] == "qpll1" else
                              Signal(),
                o_QPLL1OUTREFCLK=self.refclk if self.config["qpll"] == "qpll1" else
                                 Signal(),
                i_QPLL1PD=0 if self.config["qpll"] == "qpll1" else 1,
                i_QPLL1REFCLKSEL=0b001,
                i_QPLL1RESET=self.reset,
             )

    @staticmethod
    def compute_config(refclk_freq, linerate):
        for n in [16, 20, 32, 40, 60, 64, 66, 75, 80, 84,
                  90, 96, 100, 112, 120, 125, 150, 160]:
            for m in 1, 2, 3, 4:
                vco_freq = refclk_freq*n/m
                if 8e9 <= vco_freq <= 13e9:
                    qpll = "qpll1"
                elif 9.8e9 <= vco_freq <= 16.375e9:
                    qpll = "qpll0"
                else:
                    qpll = None
                if qpll is not None:
                    for d in 1, 2, 4, 8, 16:
                        current_linerate = (vco_freq/2)*2/d
                        if current_linerate == linerate:
                            return {"n": n, "m": m, "d": d,
                                    "vco_freq": vco_freq,
                                    "qpll": qpll,
                                    "clkin": refclk_freq,
                                    "clkout": vco_freq/2,
                                    "linerate": linerate}
        msg = "No config found for {:3.2f} MHz refclk / {:3.2f} Gbps linerate."
        raise ValueError(msg.format(refclk_freq/1e6, linerate/1e9))

    def __repr__(self):
        r = """
GTXQuadPLL
===========
  overview:
  ---------
       +-------------------------------------------------------------++
       |                                          +------------+      |
       |   +-----+  +---------------------------+ |   QPLL0    | +--+ |
       |   |     |  | Phase Frequency Detector  +->    VCO     | |  | |
CLKIN +----> /M  +-->       Charge Pump         | +------------+->/2+--> CLKOUT
       |   |     |  |       Loop Filter         +->   QPLL1    | |  | |
       |   +-----+  +---------------------------+ |    VCO     | +--+ |
       |              ^                           +-----+------+      |
       |              |        +-------+                |             |
       |              +--------+  /N   <----------------+             |
       |                       +-------+                              |
       +--------------------------------------------------------------+
                               +-------+
                      CLKOUT +->  2/D  +-> LINERATE
                               +-------+
  config:
  -------
    CLKIN    = {clkin}MHz
    CLKOUT   = CLKIN x N / (2 x M) = {clkin}MHz x {n} / (2 x {m})
             = {clkout}GHz
    VCO      = {vco_freq}GHz ({qpll})
    LINERATE = CLKOUT x 2 / D = {clkout}GHz x 2 / {d}
             = {linerate}GHz
""".format(clkin=self.config["clkin"]/1e6,
           n=self.config["n"],
           m=self.config["m"],
           clkout=self.config["clkout"]/1e9,
           vco_freq=self.config["vco_freq"]/1e9,
           qpll=self.config["qpll"].upper(),
           d=self.config["d"],
           linerate=self.config["linerate"]/1e9)
        return r


class GTHTransmitter(Module, AutoCSR):
    def __init__(self, pll, tx_pads, sys_clk_freq, polarity=0):
        self.prbs_config = Signal(2)

        self.produce_square_wave = CSRStorage()

        self.txdiffcttrl = CSRStorage(4, reset=0b1100)
        self.txmaincursor = CSRStorage(7, reset=80)
        self.txprecursor = CSRStorage(5)
        self.txpostcursor = CSRStorage(5)

        # # #

        use_cpll = isinstance(pll, GTHChannelPLL)
        use_qpll0 = isinstance(pll, GTHQuadPLL) and pll.config["qpll"] == "qpll0"
        use_qpll1 = isinstance(pll, GTHQuadPLL) and pll.config["qpll"] == "qpll1"

        self.submodules.init = GTHInit(sys_clk_freq, False)
        self.comb += [
            self.init.plllock.eq(pll.lock),
            pll.reset.eq(self.init.pllreset)
        ]

        nwords = 40//10

        txoutclk = Signal()
        txdata = Signal(40)
        gth_params = dict(
            p_ACJTAG_DEBUG_MODE              =0b0,
            p_ACJTAG_MODE                    =0b0,
            p_ACJTAG_RESET                   =0b0,
            p_ADAPT_CFG0                     =0b1111100000000000,
            p_ADAPT_CFG1                     =0b0000000000000000,
            p_ALIGN_COMMA_DOUBLE             ="FALSE",
            p_ALIGN_COMMA_ENABLE             =0b1111111111,
            p_ALIGN_COMMA_WORD               =1,
            p_ALIGN_MCOMMA_DET               ="TRUE",
            p_ALIGN_MCOMMA_VALUE             =0b1010000011,
            p_ALIGN_PCOMMA_DET               ="TRUE",
            p_ALIGN_PCOMMA_VALUE             =0b0101111100,
            p_A_RXOSCALRESET                 =0b0,
            p_A_RXPROGDIVRESET               =0b0,
            p_A_TXPROGDIVRESET               =0b0,
            p_CBCC_DATA_SOURCE_SEL           ="DECODED",
            p_CDR_SWAP_MODE_EN               =0b0,
            p_CHAN_BOND_KEEP_ALIGN           ="FALSE",
            p_CHAN_BOND_MAX_SKEW             =1,
            p_CHAN_BOND_SEQ_1_1              =0b0000000000,
            p_CHAN_BOND_SEQ_1_2              =0b0000000000,
            p_CHAN_BOND_SEQ_1_3              =0b0000000000,
            p_CHAN_BOND_SEQ_1_4              =0b0000000000,
            p_CHAN_BOND_SEQ_1_ENABLE         =0b1111,
            p_CHAN_BOND_SEQ_2_1              =0b0000000000,
            p_CHAN_BOND_SEQ_2_2              =0b0000000000,
            p_CHAN_BOND_SEQ_2_3              =0b0000000000,
            p_CHAN_BOND_SEQ_2_4              =0b0000000000,
            p_CHAN_BOND_SEQ_2_ENABLE         =0b1111,
            p_CHAN_BOND_SEQ_2_USE            ="FALSE",
            p_CHAN_BOND_SEQ_LEN              =1,
            p_CLK_CORRECT_USE                ="FALSE",
            p_CLK_COR_KEEP_IDLE              ="FALSE",
            p_CLK_COR_MAX_LAT                =12,
            p_CLK_COR_MIN_LAT                =8,
            p_CLK_COR_PRECEDENCE             ="TRUE",
            p_CLK_COR_REPEAT_WAIT            =0,
            p_CLK_COR_SEQ_1_1                =0b0100000000,
            p_CLK_COR_SEQ_1_2                =0b0100000000,
            p_CLK_COR_SEQ_1_3                =0b0100000000,
            p_CLK_COR_SEQ_1_4                =0b0100000000,
            p_CLK_COR_SEQ_1_ENABLE           =0b1111,
            p_CLK_COR_SEQ_2_1                =0b0100000000,
            p_CLK_COR_SEQ_2_2                =0b0100000000,
            p_CLK_COR_SEQ_2_3                =0b0100000000,
            p_CLK_COR_SEQ_2_4                =0b0100000000,
            p_CLK_COR_SEQ_2_ENABLE           =0b1111,
            p_CLK_COR_SEQ_2_USE              ="FALSE",
            p_CLK_COR_SEQ_LEN                =1,
            p_CPLL_CFG0                      =0b0110011111111000,
            p_CPLL_CFG1                      =0b1010010010101100,
            p_CPLL_CFG2                      =0b0000000000000111,
            p_CPLL_CFG3                      =0b000000,
            p_CPLL_FBDIV                     =1 if (use_qpll0 | use_qpll1) else pll.config["n2"],
            p_CPLL_FBDIV_45                  =4 if (use_qpll0 | use_qpll1) else pll.config["n1"],
            p_CPLL_INIT_CFG0                 =0b0000001010110010,
            p_CPLL_INIT_CFG1                 =0b00000000,
            p_CPLL_LOCK_CFG                  =0b0000000111101000,
            p_CPLL_REFCLK_DIV                =1 if (use_qpll0 | use_qpll1) else pll.config["m"],
            p_DDI_CTRL                       =0b00,
            p_DDI_REALIGN_WAIT               =15,
            p_DEC_MCOMMA_DETECT              ="TRUE",
            p_DEC_PCOMMA_DETECT              ="TRUE",
            p_DEC_VALID_COMMA_ONLY           ="FALSE",
            p_DFE_D_X_REL_POS                =0b0,
            p_DFE_VCM_COMP_EN                =0b0,
            p_DMONITOR_CFG0                  =0b0000000000,
            p_DMONITOR_CFG1                  =0b00000000,
            p_ES_CLK_PHASE_SEL               =0b0,
            p_ES_CONTROL                     =0b000000,
            p_ES_ERRDET_EN                   ="FALSE",
            p_ES_EYE_SCAN_EN                 ="FALSE",
            p_ES_HORZ_OFFSET                 =0b000000000000,
            p_ES_PMA_CFG                     =0b0000000000,
            p_ES_PRESCALE                    =0b00000,
            p_ES_QUALIFIER0                  =0b0000000000000000,
            p_ES_QUALIFIER1                  =0b0000000000000000,
            p_ES_QUALIFIER2                  =0b0000000000000000,
            p_ES_QUALIFIER3                  =0b0000000000000000,
            p_ES_QUALIFIER4                  =0b0000000000000000,
            p_ES_QUAL_MASK0                  =0b0000000000000000,
            p_ES_QUAL_MASK1                  =0b0000000000000000,
            p_ES_QUAL_MASK2                  =0b0000000000000000,
            p_ES_QUAL_MASK3                  =0b0000000000000000,
            p_ES_QUAL_MASK4                  =0b0000000000000000,
            p_ES_SDATA_MASK0                 =0b0000000000000000,
            p_ES_SDATA_MASK1                 =0b0000000000000000,
            p_ES_SDATA_MASK2                 =0b0000000000000000,
            p_ES_SDATA_MASK3                 =0b0000000000000000,
            p_ES_SDATA_MASK4                 =0b0000000000000000,
            p_EVODD_PHI_CFG                  =0b00000000000,
            p_EYE_SCAN_SWAP_EN               =0b0,
            p_FTS_DESKEW_SEQ_ENABLE          =0b1111,
            p_FTS_LANE_DESKEW_CFG            =0b1111,
            p_FTS_LANE_DESKEW_EN             ="FALSE",
            p_GEARBOX_MODE                   =0b00000,
            p_GM_BIAS_SELECT                 =0b0,
            p_LOCAL_MASTER                   =0b1,
            p_OOBDIVCTL                      =0b00,
            p_OOB_PWRUP                      =0b0,
            p_PCI3_AUTO_REALIGN              ="OVR_1K_BLK",
            p_PCI3_PIPE_RX_ELECIDLE          =0b0,
            p_PCI3_RX_ASYNC_EBUF_BYPASS      =0b00,
            p_PCI3_RX_ELECIDLE_EI2_ENABLE    =0b0,
            p_PCI3_RX_ELECIDLE_H2L_COUNT     =0b000000,
            p_PCI3_RX_ELECIDLE_H2L_DISABLE   =0b000,
            p_PCI3_RX_ELECIDLE_HI_COUNT      =0b000000,
            p_PCI3_RX_ELECIDLE_LP4_DISABLE   =0b0,
            p_PCI3_RX_FIFO_DISABLE           =0b0,
            p_PCIE_BUFG_DIV_CTRL             =0b0001000000000000,
            p_PCIE_RXPCS_CFG_GEN3            =0b0000001010100100,
            p_PCIE_RXPMA_CFG                 =0b0000000000001010,
            p_PCIE_TXPCS_CFG_GEN3            =0b0010010010100100,
            p_PCIE_TXPMA_CFG                 =0b0000000000001010,
            p_PCS_PCIE_EN                    ="FALSE",
            p_PCS_RSVD0                      =0b0000000000000000,
            p_PCS_RSVD1                      =0b000,
            p_PD_TRANS_TIME_FROM_P2          =0b000000111100,
            p_PD_TRANS_TIME_NONE_P2          =0b00011001,
            p_PD_TRANS_TIME_TO_P2            =0b01100100,
            p_PLL_SEL_MODE_GEN12             =0b00,
            p_PLL_SEL_MODE_GEN3              =0b11,
            p_PMA_RSV1                       =0b1111000000000000,
            p_PROCESS_PAR                    =0b010,
            p_RATE_SW_USE_DRP                =0b1,
            p_RESET_POWERSAVE_DISABLE        =0b0,
        )
        gth_params.update(
            p_RXBUFRESET_TIME                =0b00011,
            p_RXBUF_ADDR_MODE                ="FAST",
            p_RXBUF_EIDLE_HI_CNT             =0b1000,
            p_RXBUF_EIDLE_LO_CNT             =0b0000,
            p_RXBUF_EN                       ="TRUE",
            p_RXBUF_RESET_ON_CB_CHANGE       ="TRUE",
            p_RXBUF_RESET_ON_COMMAALIGN      ="FALSE",
            p_RXBUF_RESET_ON_EIDLE           ="FALSE",
            p_RXBUF_RESET_ON_RATE_CHANGE     ="TRUE",
            p_RXBUF_THRESH_OVFLW             =57,
            p_RXBUF_THRESH_OVRD              ="TRUE",
            p_RXBUF_THRESH_UNDFLW            =3,
            p_RXCDRFREQRESET_TIME            =0b00001,
            p_RXCDRPHRESET_TIME              =0b00001,
            p_RXCDR_CFG0                     =0b0000000000000000,
            p_RXCDR_CFG0_GEN3                =0b0000000000000000,
            p_RXCDR_CFG1                     =0b0000000000000000,
            p_RXCDR_CFG1_GEN3                =0b0000000000000000,
            p_RXCDR_CFG2                     =0b0000011101100110,
            p_RXCDR_CFG2_GEN3                =0b0000011111100110,
            p_RXCDR_CFG3                     =0b0000000000000000,
            p_RXCDR_CFG3_GEN3                =0b0000000000000000,
            p_RXCDR_CFG4                     =0b0000000000000000,
            p_RXCDR_CFG4_GEN3                =0b0000000000000000,
            p_RXCDR_CFG5                     =0b0000000000000000,
            p_RXCDR_CFG5_GEN3                =0b0000000000000000,
            p_RXCDR_FR_RESET_ON_EIDLE        =0b0,
            p_RXCDR_HOLD_DURING_EIDLE        =0b0,
            p_RXCDR_LOCK_CFG0                =0b0100010010000000,
            p_RXCDR_LOCK_CFG1                =0b0101111111111111,
            p_RXCDR_LOCK_CFG2                =0b0111011111000011,
            p_RXCDR_PH_RESET_ON_EIDLE        =0b0,
            p_RXCFOK_CFG0                    =0b0100000000000000,
            p_RXCFOK_CFG1                    =0b0000000001100101,
            p_RXCFOK_CFG2                    =0b0000000000101110,
            p_RXDFELPMRESET_TIME             =0b0001111,
            p_RXDFELPM_KL_CFG0               =0b0000000000000000,
            p_RXDFELPM_KL_CFG1               =0b0000000000110010,
            p_RXDFELPM_KL_CFG2               =0b0000000000000000,
            p_RXDFE_CFG0                     =0b0000101000000000,
            p_RXDFE_CFG1                     =0b0000000000000000,
            p_RXDFE_GC_CFG0                  =0b0000000000000000,
            p_RXDFE_GC_CFG1                  =0b0111100001110000,
            p_RXDFE_GC_CFG2                  =0b0000000000000000,
            p_RXDFE_H2_CFG0                  =0b0000000000000000,
            p_RXDFE_H2_CFG1                  =0b0000000000000000,
            p_RXDFE_H3_CFG0                  =0b0100000000000000,
            p_RXDFE_H3_CFG1                  =0b0000000000000000,
            p_RXDFE_H4_CFG0                  =0b0010000000000000,
            p_RXDFE_H4_CFG1                  =0b0000000000000011,
            p_RXDFE_H5_CFG0                  =0b0010000000000000,
            p_RXDFE_H5_CFG1                  =0b0000000000000011,
            p_RXDFE_H6_CFG0                  =0b0010000000000000,
            p_RXDFE_H6_CFG1                  =0b0000000000000000,
            p_RXDFE_H7_CFG0                  =0b0010000000000000,
            p_RXDFE_H7_CFG1                  =0b0000000000000000,
            p_RXDFE_H8_CFG0                  =0b0010000000000000,
            p_RXDFE_H8_CFG1                  =0b0000000000000000,
            p_RXDFE_H9_CFG0                  =0b0010000000000000,
            p_RXDFE_H9_CFG1                  =0b0000000000000000,
            p_RXDFE_HA_CFG0                  =0b0010000000000000,
            p_RXDFE_HA_CFG1                  =0b0000000000000000,
            p_RXDFE_HB_CFG0                  =0b0010000000000000,
            p_RXDFE_HB_CFG1                  =0b0000000000000000,
            p_RXDFE_HC_CFG0                  =0b0000000000000000,
            p_RXDFE_HC_CFG1                  =0b0000000000000000,
            p_RXDFE_HD_CFG0                  =0b0000000000000000,
            p_RXDFE_HD_CFG1                  =0b0000000000000000,
            p_RXDFE_HE_CFG0                  =0b0000000000000000,
            p_RXDFE_HE_CFG1                  =0b0000000000000000,
            p_RXDFE_HF_CFG0                  =0b0000000000000000,
            p_RXDFE_HF_CFG1                  =0b0000000000000000,
            p_RXDFE_OS_CFG0                  =0b1000000000000000,
            p_RXDFE_OS_CFG1                  =0b0000000000000000,
            p_RXDFE_UT_CFG0                  =0b1000000000000000,
            p_RXDFE_UT_CFG1                  =0b0000000000000011,
            p_RXDFE_VP_CFG0                  =0b1010101000000000,
            p_RXDFE_VP_CFG1                  =0b0000000000110011,
            p_RXDLY_CFG                      =0b0000000000011111,
            p_RXDLY_LCFG                     =0b0000000000110000,
            p_RXELECIDLE_CFG                 ="SIGCFG_4",
            p_RXGBOX_FIFO_INIT_RD_ADDR       =4,
            p_RXGEARBOX_EN                   ="FALSE",
            p_RXISCANRESET_TIME              =0b00001,
            p_RXLPM_CFG                      =0b0000000000000000,
            p_RXLPM_GC_CFG                   =0b0001000000000000,
            p_RXLPM_KH_CFG0                  =0b0000000000000000,
            p_RXLPM_KH_CFG1                  =0b0000000000000010,
            p_RXLPM_OS_CFG0                  =0b1000000000000000,
            p_RXLPM_OS_CFG1                  =0b0000000000000010,
            p_RXOOB_CFG                      =0b000000110,
            p_RXOOB_CLK_CFG                  ="PMA",
            p_RXOSCALRESET_TIME              =0b00011,
            p_RXOUT_DIV                      =pll.config["d"],
            p_RXPCSRESET_TIME                =0b00011,
            p_RXPHBEACON_CFG                 =0b0000000000000000,
            p_RXPHDLY_CFG                    =0b0010000000100000,
            p_RXPHSAMP_CFG                   =0b0010000100000000,
            p_RXPHSLIP_CFG                   =0b0110011000100010,
            p_RXPH_MONITOR_SEL               =0b00000,
            p_RXPI_CFG0                      =0b01,
            p_RXPI_CFG1                      =0b01,
            p_RXPI_CFG2                      =0b01,
            p_RXPI_CFG3                      =0b01,
            p_RXPI_CFG4                      =0b1,
            p_RXPI_CFG5                      =0b1,
            p_RXPI_CFG6                      =0b011,
            p_RXPI_LPM                       =0b0,
            p_RXPI_VREFSEL                   =0b0,
            p_RXPMACLK_SEL                   ="DATA",
            p_RXPMARESET_TIME                =0b00011,
            p_RXPRBS_ERR_LOOPBACK            =0b0,
            p_RXPRBS_LINKACQ_CNT             =15,
            p_RXSLIDE_AUTO_WAIT              =7,
            p_RXSLIDE_MODE                   ="OFF",
            p_RXSYNC_MULTILANE               =0b0,
            p_RXSYNC_OVRD                    =0b0,
            p_RXSYNC_SKIP_DA                 =0b0,
            p_RX_AFE_CM_EN                   =0b0,
            p_RX_BIAS_CFG0                   =0b0000101010110100,
            p_RX_BUFFER_CFG                  =0b000000,
            p_RX_CAPFF_SARC_ENB              =0b0,
            p_RX_CLK25_DIV                   =5,
            p_RX_CLKMUX_EN                   =0b1,
            p_RX_CLK_SLIP_OVRD               =0b00000,
            p_RX_CM_BUF_CFG                  =0b1010,
            p_RX_CM_BUF_PD                   =0b0,
            p_RX_CM_SEL                      =0b11,
            p_RX_CM_TRIM                     =0b1010,
            p_RX_CTLE3_LPF                   =0b00000001,
            p_RX_DATA_WIDTH                  =40,
            p_RX_DDI_SEL                     =0b000000,
            p_RX_DEFER_RESET_BUF_EN          ="TRUE",
            p_RX_DFELPM_CFG0                 =0b0110,
            p_RX_DFELPM_CFG1                 =0b1,
            p_RX_DFELPM_KLKH_AGC_STUP_EN     =0b1,
            p_RX_DFE_AGC_CFG0                =0b10,
            p_RX_DFE_AGC_CFG1                =0b000,
            p_RX_DFE_KL_LPM_KH_CFG0          =0b01,
            p_RX_DFE_KL_LPM_KH_CFG1          =0b000,
            p_RX_DFE_KL_LPM_KL_CFG0          =0b01,
            p_RX_DFE_KL_LPM_KL_CFG1          =0b000,
            p_RX_DFE_LPM_HOLD_DURING_EIDLE   =0b0,
            p_RX_DISPERR_SEQ_MATCH           ="TRUE",
            p_RX_DIVRESET_TIME               =0b00001,
            p_RX_EN_HI_LR                    =0b0,
            p_RX_EYESCAN_VS_CODE             =0b0000000,
            p_RX_EYESCAN_VS_NEG_DIR          =0b0,
            p_RX_EYESCAN_VS_RANGE            =0b00,
            p_RX_EYESCAN_VS_UT_SIGN          =0b0,
            p_RX_FABINT_USRCLK_FLOP          =0b0,
            p_RX_INT_DATAWIDTH               =1,
            p_RX_PMA_POWER_SAVE              =0b0,
            p_RX_PROGDIV_CFG                 =0.0,
            p_RX_SAMPLE_PERIOD               =0b111,
            p_RX_SIG_VALID_DLY               =11,
            p_RX_SUM_DFETAPREP_EN            =0b0,
            p_RX_SUM_IREF_TUNE               =0b1100,
            p_RX_SUM_RES_CTRL                =0b11,
            p_RX_SUM_VCMTUNE                 =0b0000,
            p_RX_SUM_VCM_OVWR                =0b0,
            p_RX_SUM_VREF_TUNE               =0b000,
            p_RX_TUNE_AFE_OS                 =0b10,
            p_RX_WIDEMODE_CDR                =0b0,
            p_RX_XCLK_SEL                    ="RXDES",
            p_SAS_MAX_COM                    =64,
            p_SAS_MIN_COM                    =36,
            p_SATA_BURST_SEQ_LEN             =0b1110,
            p_SATA_CPLL_CFG                  ="VCO_3000MHZ",
            p_SATA_MAX_BURST                 =8,
            p_SATA_MAX_INIT                  =21,
            p_SATA_MAX_WAKE                  =7,
            p_SATA_MIN_BURST                 =4,
            p_SATA_MIN_INIT                  =12,
            p_SATA_MIN_WAKE                  =4,
            p_SHOW_REALIGN_COMMA             ="TRUE",
            p_SIM_RECEIVER_DETECT_PASS       ="TRUE",
            p_SIM_RESET_SPEEDUP              ="TRUE",
            p_SIM_TX_EIDLE_DRIVE_LEVEL       =0b0,
            p_SIM_VERSION                    =2,
            p_TAPDLY_SET_TX                  =0b00,
            p_TEMPERATUR_PAR                 =0b0010,
            p_TERM_RCAL_CFG                  =0b100001000010000,
            p_TERM_RCAL_OVRD                 =0b000,
            p_TRANS_TIME_RATE                =0b00001110,
            p_TST_RSV0                       =0b00000000,
            p_TST_RSV1                       =0b00000000,
        )
        gth_params.update(
            p_TXBUF_EN                       ="TRUE",
            p_TXBUF_RESET_ON_RATE_CHANGE     ="TRUE",
            p_TXDLY_CFG                      =0b0000000000001001,
            p_TXDLY_LCFG                     =0b0000000001010000,
            p_TXDRVBIAS_N                    =0b1010,
            p_TXDRVBIAS_P                    =0b1010,
            p_TXFIFO_ADDR_CFG                ="LOW",
            p_TXGBOX_FIFO_INIT_RD_ADDR       =4,
            p_TXGEARBOX_EN                   ="FALSE",
            p_TXOUT_DIV                      =pll.config["d"],
            p_TXPCSRESET_TIME                =0b00011,
            p_TXPHDLY_CFG0                   =0b0010000000100000,
            p_TXPHDLY_CFG1                   =0b0000000001110101,
            p_TXPH_CFG                       =0b0000100110000000,
            p_TXPH_MONITOR_SEL               =0b00000,
            p_TXPI_CFG0                      =0b00,
            p_TXPI_CFG1                      =0b00,
            p_TXPI_CFG2                      =0b00,
            p_TXPI_CFG3                      =0b1,
            p_TXPI_CFG4                      =0b1,
            p_TXPI_CFG5                      =0b000,
            p_TXPI_GRAY_SEL                  =0b0,
            p_TXPI_INVSTROBE_SEL             =0b0,
            p_TXPI_LPM                       =0b0,
            p_TXPI_PPMCLK_SEL                ="TXUSRCLK2",
            p_TXPI_PPM_CFG                   =0b00000000,
            p_TXPI_SYNFREQ_PPM               =0b001,
            p_TXPI_VREFSEL                   =0b0,
            p_TXPMARESET_TIME                =0b00011,
            p_TXSYNC_MULTILANE               =0,
            p_TXSYNC_OVRD                    =0b0,
            p_TXSYNC_SKIP_DA                 =0b0,
            p_TX_CLK25_DIV                   =5,
            p_TX_CLKMUX_EN                   =0b1,
            p_TX_DATA_WIDTH                  =40,
            p_TX_DCD_CFG                     =0b000010,
            p_TX_DCD_EN                      =0b0,
            p_TX_DEEMPH0                     =0b000000,
            p_TX_DEEMPH1                     =0b000000,
            p_TX_DIVRESET_TIME               =0b00001,
            p_TX_DRIVE_MODE                  ="DIRECT",
            p_TX_EIDLE_ASSERT_DELAY          =0b100,
            p_TX_EIDLE_DEASSERT_DELAY        =0b011,
            p_TX_EML_PHI_TUNE                =0b0,
            p_TX_FABINT_USRCLK_FLOP          =0b0,
            p_TX_IDLE_DATA_ZERO              =0b0,
            p_TX_INT_DATAWIDTH               =1,
            p_TX_LOOPBACK_DRIVE_HIZ          ="FALSE",
            p_TX_MAINCURSOR_SEL              =0b0,
            p_TX_MARGIN_FULL_0               =0b1001111,
            p_TX_MARGIN_FULL_1               =0b1001110,
            p_TX_MARGIN_FULL_2               =0b1001100,
            p_TX_MARGIN_FULL_3               =0b1001010,
            p_TX_MARGIN_FULL_4               =0b1001000,
            p_TX_MARGIN_LOW_0                =0b1000110,
            p_TX_MARGIN_LOW_1                =0b1000101,
            p_TX_MARGIN_LOW_2                =0b1000011,
            p_TX_MARGIN_LOW_3                =0b1000010,
            p_TX_MARGIN_LOW_4                =0b1000000,
            p_TX_MODE_SEL                    =0b000,
            p_TX_PMADATA_OPT                 =0b0,
            p_TX_PMA_POWER_SAVE              =0b0,
            p_TX_PROGCLK_SEL                 ="PREPI",
            p_TX_PROGDIV_CFG                 =0.0,
            p_TX_QPI_STATUS_EN               =0b0,
            p_TX_RXDETECT_CFG                =0b00000000110010,
            p_TX_RXDETECT_REF                =0b100,
            p_TX_SAMPLE_PERIOD               =0b111,
            p_TX_SARC_LPBK_ENB               =0b0,
            p_TX_XCLK_SEL                    ="TXUSR",
            p_USE_PCS_CLK_PHASE_SEL          =0b0,
            p_WB_MODE                        =0b00,
        )
        gth_params.update(
            # Reset modes
            i_GTRESETSEL=0,
            i_RESETOVRD=0,

            # CPLL
            i_CPLLRESET=0,
            i_CPLLPD=0 if (use_qpll0 | use_qpll1) else pll.reset,
            o_CPLLLOCK=Signal() if (use_qpll0 | use_qpll1) else pll.lock,
            i_CPLLLOCKEN=1,
            i_CPLLREFCLKSEL=0b001,
            i_TSTIN=2**20-1,
            i_GTREFCLK0=0 if (use_qpll0 | use_qpll1) else pll.refclk,

            # QPLL
            i_QPLL0CLK=0 if (use_cpll | use_qpll1) else pll.clk,
            i_QPLL0REFCLK=0 if (use_cpll | use_qpll1) else pll.refclk,
            i_QPLL1CLK=0 if (use_cpll | use_qpll0) else pll.clk,
            i_QPLL1REFCLK=0 if (use_cpll | use_qpll0) else pll.refclk,

            # TX clock
            o_TXOUTCLK=txoutclk,
            i_TXSYSCLKSEL=0b00 if use_cpll else 0b10 if use_qpll0 else 0b11,
            i_TXPLLCLKSEL=0b00 if use_cpll else 0b11 if use_qpll0 else 0b10,
            i_TXOUTCLKSEL=0b11,

            # disable RX
            i_RXPD=0b11,

            # Startup/Reset
            i_GTTXRESET=self.init.gtXxreset,
            o_TXRESETDONE=self.init.Xxresetdone,
            i_TXDLYSRESET=self.init.Xxdlysreset,
            o_TXDLYSRESETDONE=self.init.Xxdlysresetdone,
            o_TXPHALIGNDONE=self.init.Xxphaligndone,
            i_TXUSERRDY=1,

            # TX data
            i_TXCTRL0=Cat(*[txdata[10*i+8] for i in range(nwords)]),
            i_TXCTRL1=Cat(*[txdata[10*i+9] for i in range(nwords)]),
            i_TXDATA=Cat(*[txdata[10*i:10*i+8] for i in range(nwords)]),
            i_TXUSRCLK=ClockSignal("tx"),
            i_TXUSRCLK2=ClockSignal("tx"),

            # TX electrical
            i_TXBUFDIFFCTRL=0b000,
            i_TXDIFFCTRL=self.txdiffcttrl.storage,
            i_TXMAINCURSOR=self.txmaincursor.storage,
            i_TXPRECURSOR=self.txprecursor.storage,
            i_TXPOSTCURSOR=self.txpostcursor.storage,

            # Polarity
            i_TXPOLARITY=polarity,

            # Pads
            o_GTHTXP=tx_pads.txp,
            o_GTHTXN=tx_pads.txn
        )
        self.specials += Instance("GTHE3_CHANNEL", **gth_params)

        self.clock_domains.cd_tx = ClockDomain()
        self.specials += Instance("BUFG_GT",
            i_I=txoutclk, o_O=self.cd_tx.clk)
        self.specials += AsyncResetSynchronizer(
            self.cd_tx, ~self.init.done)

        self.submodules.encoder = ClockDomainsRenamer("tx")(Encoder(nwords, True))
        self.submodules.prbs = ClockDomainsRenamer("tx")(PRBSTX(40, True))
        self.comb += [
            self.prbs.config.eq(self.prbs_config),
            self.prbs.i.eq(Cat(*[self.encoder.output[i] for i in range(nwords)])),
            If(self.produce_square_wave.storage,
                # square wave @ linerate/40 for scope observation
                txdata.eq(0b1111111111111111111100000000000000000000)
            ).Else(
                txdata.eq(self.prbs.o)
            )
        ]
