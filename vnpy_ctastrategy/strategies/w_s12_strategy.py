import math
from typing import Any
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from vnpy_ctastrategy import (
    CtaTemplate,
    StopOrder,
    TickData,
    BarData,
    TradeData,
    OrderData,
    BarGenerator,
    ArrayManager,
)
from vnpy.trader.constant import Exchange, Interval, Status
from tqsdk import tafunc


class WS12Strategy(CtaTemplate):
    """"""

    author = "Weo"
    fixed_size: int = 1

    len: int = 250
    stpr: int = 20
    n: int = 70

    vlt: float = 0.0
    ma_vlt: float = 0.0
    turn_tag: int = 0
    fd1: float = 0.0
    fd2: float = 0.0
    zd: int = 0
    bsr: float = 0.0
    bsl: float = 0.0
    mbl: float = 0.0
    msl: float = 0.0
    op_l: int = 0
    op_s: int = 0
    op: int = 0
    dk: int = 0
    vwap: float = 0.0

    parameters = ["len", "stpr", "n"]
    variables = ["vlt", "ma_vlt", "turn_tag", "fd1", "fd2", "zd", "bsr", "bsl", "mbl", "msl", "op_l", "op_s", "op",
                 "dk", "vwap"]

    def __init__(self, cta_engine: Any, strategy_name: str, vt_symbol: str, setting: dict, minuteWindow: int) -> None:
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.minuteWindow = minuteWindow

    def on_init(self) -> None:
        """
        Callback when strategy is inited.
        """
        self.write_log(f"策略{self.strategy_name}初始化，symbol={self.vt_symbol}，分钟周期={self.minuteWindow}")

        self.bg = BarGenerator(self.on_bar, self.minuteWindow, self.on_min_bar, Interval.MINUTE5)
        self.kline_len_per_day = self.cal_kline_len_single_day()
        # kline_len = max(self.len, self.kline_len_per_day * self.n) + 2000  # 指标管理器计算所需K线数量，多预留2000根
        kline_len = 2 * 244 * self.kline_len_per_day  # 指标管理器计算所需K线数量，此处设为缓存2年数据（一年约244个交易日）
        self.am = ArrayManager(kline_len, self.cta_engine)

        # 全局变量初始化
        self.in_trade_list = np.zeros(kline_len)  # 记录是否处于交易当中

        self.load_bar(365 * 2, interval=Interval.MINUTE5)  # 预加载2年1个月数据（自然日）

    def on_start(self) -> None:
        """
        Callback when strategy is started.
        """
        self.write_log("策略启动")

    def on_stop(self) -> None:
        """
        Callback when strategy is stopped.
        """
        self.write_log("策略停止")

    def on_tick(self, tick: TickData) -> None:
        """
        Callback of new tick data update.
        """
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        """
        Callback of new bar data update.
        """
        self.bg.update_bar(bar, 1)

    def on_min_bar(self, bar: BarData) -> None:
        """"""
        self.cancel_all()

        am = self.am
        am.update_bar(bar)
        self.addItem_in_trade(self.in_trade_list[-1] if len(self.in_trade_list) > 0 else 0)  # 添加一个前值（下面会更新）
        if not am.inited:
            return

        _zd = self.get_zd()

        datetime_array = self.am.datetime  # K线开始时间
        close_datetime_array = self.am.close_datetime  # K线结束时间
        close_array = self.am.close
        low_array = self.am.low
        high_array = self.am.high
        vol_array = self.am.volume
        df = pd.DataFrame()
        df['datetime'] = datetime_array
        df['close'] = close_array
        df['low'] = low_array
        df['high'] = high_array
        df['volume'] = vol_array
        buy_v = pd.Series(np.where(df["close"] > df["close"].shift(1), df["volume"], 0)).rolling(self.len).sum()
        sell_v = pd.Series(np.where(df["close"] < df["close"].shift(1), df["volume"], 0)).rolling(self.len).sum()
        _bsr = self.cta_round(buy_v / sell_v, 4)
        self.bsr = _bsr.iloc[-1]
        _bsl = pd.Series([_bsr.iloc[i - 1] if i > 0 and close_datetime_array[i - 1].hour == 15 else np.nan for i in
                          range(len(datetime_array))])
        for i in range(1, len(_bsl)):
            if np.isnan(_bsl.iloc[i]) and not np.isnan(_bsl.iloc[i - 1]):
                _bsl.iloc[i] = _bsl.iloc[i - 1]
        self.bsl = _bsl.iloc[-1]
        _mbl = pd.Series([max(v, 1) for v in _bsl])
        self.mbl = _mbl.iloc[-1]
        _msl = pd.Series([min(v, 1) for v in _bsl])
        self.msl = _msl.iloc[-1]

        crossup_bsr_mbl = pd.Series(
            [_bsr.iloc[i - 1] <= _mbl.iloc[i - 1] and _bsr.iloc[i] > _mbl.iloc[i] and self.in_trade_list[
                i - 1] == 0 if i > 0 else False for i in range(len(_bsr))])
        _op_l = tafunc.barlast(crossup_bsr_mbl)
        self.op_l = _op_l.iloc[-1]
        crossdown_bsr_msl = pd.Series([
            _bsr.iloc[i - 1] >= _msl.iloc[i - 1] and _bsr.iloc[i] < _msl.iloc[i] and self.in_trade_list[
                i - 1] == 0 if i > 0 else False for i in range(len(_bsr))])
        _op_s = tafunc.barlast(crossdown_bsr_msl)
        self.op_s = _op_s.iloc[-1]
        op_temp1 = [True if not np.isnan(_op_l.iloc[i]) and not np.isnan(_op_s.iloc[i]) else False for i in
                    range(len(_op_l))]
        _op = pd.Series(np.where(op_temp1, np.minimum(_op_l, _op_s),
                                 np.where(np.isnan(_op_l), _op_s, np.where(np.isnan(_op_s), _op_l, -1))))
        dk = np.where(_op_l == 0, 1, np.where(_op_s == 0, -1, np.nan))
        # dk特殊处理：当等于nan时取前一个有效值
        for i in range(1, len(dk)):
            if np.isnan(dk[i]) and not np.isnan(dk[i - 1]):
                dk[i] = dk[i - 1]

        print(f'\n>>>>>>datetime={bar.datetime}')
        self.printData('close_array', close_array[-5:])
        # self.printData('low_array', low_array[-5:])
        # self.printData('high_array', high_array[-5:])
        self.printData('vol_array', vol_array[-5:])
        self.printData('_zd', _zd[-5:])
        # self.printData('buy_v', buy_v.iloc[-5:])
        # self.printData('sell_v'， sell_v.iloc[-5:])
        self.printData('_bsr', _bsr.iloc[-5:])
        # self.printData('_bsl', _bsl.iloc[-5:])
        self.printData('_mbl', _mbl.iloc[-5:])
        self.printData('_msl', _msl.iloc[-5:])
        # self.printData('_op_l', _op_l.iloc[-5:])
        # self.printData('_op_s', _op_s.iloc[-5:])
        self.printData('_op', _op.iloc[-5:])
        self.printData('dk', dk[-5:])
        self.printData('in_trade_list', self.in_trade_list[-5:])

        if bar.datetime.strftime("%Y-%m-%d %H:%M:%S") == '2024-01-05 14:15:00':
            print()

        if (self.trading and self.pos == 0 and self.virtual_pos == 0) or (not self.trading and self.virtual_pos == 0):
            bkcon = _op_l.iloc[-1] == 0 and _zd[-1] == 0
            skcon = _op_s.iloc[-1] == 0 and _zd[-1] == 0
            print(f'========== pos==0 ==========' if self.trading else
                  f'========== virtual_pos={self.virtual_pos} ==========')
            print(f'bkcon={bkcon}, skcon={skcon}')
            if bkcon:
                self.buy(bar.close_price, self.fixed_size, False)
                self.in_trade_list[-1] = 1
                print(f'买开 {bar.datetime}')
            elif skcon:
                self.short(bar.close_price, self.fixed_size, False)
                self.in_trade_list[-1] = 1
                print(f'卖开 {bar.datetime}')

        elif (self.trading and (self.pos != 0 or self.virtual_pos != 0)) or (not self.trading and self.virtual_pos != 0):
            open_p = _op.iloc[-1]
            stbar = 40
            """JP:=IF(DK=1,HV(L,OPEN_P),IF(DK=-1,LV(H,OPEN_P),NULL))"""
            jp = pd.Series([max(low_array[-1 - open_p: -1 - open_p + i]) if dk[-1] == 1 else
                            min(high_array[-1 - open_p: -1 - open_p + i])
                            for i in range(1, open_p + 1)])
            vp = self.cta_round(jp * (1 - self.stpr / 1000 if dk[-1] == 1 else 1 + self.stpr / 1000))
            cn = open_p
            sum_vol = pd.Series(vol_array).iloc[-cn:].sum()
            print(f'----parameters={self.get_parameters()}; vp.shape={vp.shape}')
            if vp.shape[0] != vol_array[-cn:].shape[0]:
                print(f'----shape1={vol_array[-cn:].shape}')
                return
            sum_amt = self.cta_round((pd.Series(vol_array[-cn:] * vp.tolist())).sum())
            out_price = self.cta_round(sum_amt / sum_vol)
            vwap = vp.iloc[-1] if open_p >= stbar else out_price

            print(f'========== pos!=0 ==========' if self.trading else
                  f'========== virtual_pos={self.virtual_pos} ==========')
            self.printData('jp', jp.iloc[-5:])
            print(f'>>open_p={open_p}')
            print(f'>>vwap={vwap}')

            if (self.trading and (self.pos > 0 or self.virtual_pos > 0)) or (not self.trading and self.virtual_pos > 0):
                # 转震荡平仓
                spcon = _zd[-2] == 0 and _zd[-1] == 1 and dk[-1] == 1
                if spcon:
                    self.sell(bar.close_price, abs(self.pos), False)
                    self.in_trade_list[-1] = 0
                    print(f'卖平 {bar.datetime}')
                # 动态出场
                pcon_l = dk[-1] == 1 and low_array[-1] <= vwap
                if pcon_l:
                    self.sell(bar.close_price, abs(self.pos), False)
                    self.in_trade_list[-1] = 0
                    print(f'卖平 {bar.datetime}')

            elif (self.trading and (self.pos < 0 or self.virtual_pos < 0)) or (not self.trading and self.virtual_pos < 0):
                # 转震荡平仓
                bpcon = _zd[-2] == 0 and _zd[-1] == 1 and dk[-1] == -1
                if bpcon:
                    self.cover(bar.close_price, abs(self.pos), False)
                    self.in_trade_list[-1] = 0
                    print(f'买平 {bar.datetime}')
                # 动态出场
                pcon_s = dk[-1] == -1 and high_array[-1] >= vwap
                if pcon_s:
                    self.cover(bar.close_price, abs(self.pos), False)
                    self.in_trade_list[-1] = 0
                    print(f'买平 {bar.datetime}')

        self.put_event()

    def on_order(self, order: OrderData) -> None:
        """
        Callback of new order data update.
        """
        if order is not None:
            if order.status == Status.CANCELLED:
                self.in_trade_list[-1] = 0  # 撤销委托（可能是下一根K线价格达不到委托价导致成交不了），重置状态

    def on_trade(self, trade: TradeData) -> None:
        """
        Callback of new trade data update.
        """
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        """
        Callback of stop order update.
        """
        pass

    def cal_kline_len_single_day(self):
        """计算单日分钟K线数量"""

        bars: list[BarData] = self.cta_engine.load_bar(
            self.vt_symbol,
            20,
            Interval.MINUTE5,
            None,
            False
        )  # 可以多取几天，防止长假的情况
        if bars:
            cal_day = 3  # 取最近3个交易日
            already_cal_day = 0
            kline_len_per_day: list[int] = []
            start_index = -1
            end_index = -1
            for i in range(len(bars) - 1, -1, -1):
                if bars[i].datetime.hour == 14 and bars[i].datetime.minute == 55 and bars[i].datetime.second == 0:
                    end_index = i
                elif (bars[i].datetime.hour == 21 and bars[i].datetime.minute == 0 and bars[i].datetime.second == 0
                      and end_index != -1):
                    start_index = i
                if start_index != -1 and end_index != -1:
                    already_cal_day = already_cal_day + 1
                    kline_len_per_day.append(end_index - start_index + 1)  # 计算单个交易日所含K线数量
                    start_index = -1
                    end_index = -1
                    if already_cal_day >= cal_day:
                        break

            len_min = self.minuteWindow / 5  # 策略指定分钟周期相对于5分钟的倍数
            return math.ceil(max(kline_len_per_day) / len_min)

    def get_zd(self):
        """获取是否为震荡"""
        close_array = self.am.close
        # zf_temp_array = close_array[1:] / close_array[:-1]  # 这里不用处理保留小数位，因为对ln取对数的运算影响较大
        zf_temp_array = [close_array[i] / close_array[i - 1] if i > 0 and close_array[i - 1] > 0 else np.nan for i in
                         range(len(close_array))]  # 这里不用处理保留小数位，因为对ln取对数的运算影响较大
        zf_array = pd.Series(self.cta_round(np.log(zf_temp_array) * 100))
        _vlt = self.cta_round(
            tafunc.std(zf_array, self.kline_len_per_day * self.n) * math.sqrt(252 * self.kline_len_per_day), 4)
        self.vlt = _vlt.iloc[-1]
        _ma_vlt = self.cta_round(tafunc.ma(_vlt, math.floor(self.n / 3) * self.kline_len_per_day), 4)
        self.ma_vlt = _ma_vlt.iloc[-1]
        ln1 = max(3, math.floor(self.kline_len_per_day / 2))

        # 波动率波峰/波谷拐点
        bf_right = tafunc.ref(_ma_vlt, ln1) > tafunc.hhv(_ma_vlt, ln1)  # 波峰结构的右边
        bg_right = tafunc.ref(_ma_vlt, ln1) < tafunc.llv(_ma_vlt, ln1)  # 波谷结构的右边
        with pd.option_context('future.no_silent_downcasting', True):
            bf_left = tafunc.ref(_ma_vlt >= tafunc.ref(tafunc.hhv(_ma_vlt, ln1), 1), ln1).fillna(False).infer_objects(
                copy=False)
            bf_left2 = tafunc.ref(_ma_vlt >= tafunc.ref(tafunc.hhv(_ma_vlt, 20 * self.kline_len_per_day), 1),
                                  ln1).fillna(False).infer_objects(copy=False)
            bg_left = tafunc.ref(_ma_vlt <= tafunc.ref(tafunc.llv(_ma_vlt, ln1), 1), ln1).fillna(False).infer_objects(
                copy=False)
            bg_left2 = tafunc.ref(_ma_vlt <= tafunc.ref(tafunc.llv(_ma_vlt, 20 * self.kline_len_per_day), 1),
                                  ln1).fillna(False).infer_objects(copy=False)
        _turn_tag = pd.Series(
            np.where(bf_right & bf_left & bf_left2, 1, np.where(bg_right & bg_left & bg_left2, -1, np.nan)))
        self.turn_tag = _turn_tag.iloc[-1]

        hvlt_temp = tafunc.barlast(_turn_tag == 1)
        hvlt = pd.Series([_ma_vlt.iloc[i - hvlt_temp.iloc[i] - ln1] if hvlt_temp.iloc[i] != -1 else np.nan for i in
                          range(len(hvlt_temp))])
        lvlt_temp = tafunc.barlast(_turn_tag == -1)
        lvlt = pd.Series([_ma_vlt.iloc[i - lvlt_temp.iloc[i] - ln1] if lvlt_temp.iloc[i] != -1 else np.nan for i in
                          range(len(lvlt_temp))])
        ln2 = 20
        _fd1 = self.cta_round(np.where(_turn_tag == 1, (hvlt / lvlt - 1) * 100, np.nan))
        self.fd1 = _fd1[-1]
        _fd2 = self.cta_round(np.where(_turn_tag == -1, (lvlt / hvlt - 1) * 100, np.nan))
        self.fd2 = _fd2[-1]
        _zd = np.where(_fd1 >= ln2, 1, np.where(_fd2 <= -ln2, 0, np.nan))
        # zd特殊处理1：当等于nan时取前一个有效值
        for i in range(1, len(_zd)):
            if np.isnan(_zd[i]) and not np.isnan(_zd[i - 1]):
                _zd[i] = _zd[i - 1]
        # zd特殊处理2：起始段的nan置为0，否则会出现由于加载数据不足导致起始段zd值为nan的情况
        _zd = np.nan_to_num(_zd)
        self.zd = _zd[-1]

        if self.am.datetime[-1].strftime("%Y-%m-%d %H:%M:%S") == '2024-01-04 21:00:00':
            print()

        return _zd

    def cta_round(self, value: pd.Series | np.ndarray | list, digitNum=2):
        if value is not None:
            return np.around(value, digitNum)

    def addItem_in_trade(self, in_trade_tag):
        if len(self.in_trade_list) < self.am.size:
            self.in_trade_list.append(in_trade_tag)
        else:
            self.in_trade_list[:-1] = self.in_trade_list[1:]
            self.in_trade_list[-1] = in_trade_tag

    def printData(self, name, datas: pd.Series | np.ndarray | list):
        if datas is not None:
            # print(f'>>{name}.size={len(datas)}')
            if isinstance(datas, pd.Series):
                print(f'>>{name}.value={datas.tolist()}')
            elif isinstance(datas, (np.ndarray, list)):
                print(f'>>{name}.value={datas}')
