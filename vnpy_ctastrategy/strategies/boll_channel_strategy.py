from datetime import datetime

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
from vnpy.trader.constant import Exchange, Interval


class BollChannelStrategy(CtaTemplate):
    """"""

    author = "用Python的交易员"

    boll_window: float = 18
    boll_dev: float = 3.4
    cci_window: int = 10
    atr_window: int = 30
    sl_multiplier: float = 5.2
    fixed_size: int = 1

    boll_up: float = 0
    boll_down: float = 0
    cci_value: float = 0
    atr_value: float = 0
    intra_trade_high: float = 0
    intra_trade_low: float = 0
    long_stop: float = 0
    short_stop: float = 0

    parameters = [
        "boll_window",
        "boll_dev",
        "cci_window",
        "atr_window",
        "sl_multiplier",
        "fixed_size"
    ]
    variables = [
        "boll_up",
        "boll_down",
        "cci_value",
        "atr_value",
        "intra_trade_high",
        "intra_trade_low",
        "long_stop",
        "short_stop"
    ]

    def on_init(self) -> None:
        """
        Callback when strategy is inited.
        """
        self.write_log("策略初始化")

        self.bg = BarGenerator(self.on_bar, 15, self.on_15min_bar, Interval.MINUTE5)
        self.am = ArrayManager()

        self.load_bar(10)

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
        self.bg.update_bar(bar)
        # print(f"{datetime.now()}\t更新K线{bar.datetime}")

    def on_15min_bar(self, bar: BarData) -> None:
        """"""
        # print(f"{datetime.now()}\ton_15min_bar\t{bar.datetime}")
        self.cancel_all()

        am = self.am
        am.update_bar(bar)
        if not am.inited:
            return

        self.boll_up, self.boll_down = am.boll(self.boll_window, self.boll_dev)
        self.cci_value = am.cci(self.cci_window)
        self.atr_value = am.atr(self.atr_window)

        if self.pos == 0:
            self.intra_trade_high = bar.high_price
            self.intra_trade_low = bar.low_price

            if self.cci_value > 0:
                self.buy(self.boll_up, self.fixed_size, True)
                print(f'--开多：{bar.datetime}\tboll_up={self.boll_up}\tboll_down={self.boll_down}\tcci={self.cci_value}'
                      f'\tatr={self.atr_value}')
            elif self.cci_value < 0:
                self.short(self.boll_down, self.fixed_size, True)
                print(f'--开空：{bar.datetime}\tboll_up={self.boll_up}\tboll_down={self.boll_down}\tcci={self.cci_value}'
                      f'\tatr={self.atr_value}')

        elif self.pos > 0:
            self.intra_trade_high = max(self.intra_trade_high, bar.high_price)
            self.intra_trade_low = bar.low_price

            self.long_stop = self.intra_trade_high - self.atr_value * self.sl_multiplier
            self.sell(self.long_stop, abs(self.pos), True)
            print(f'--平多：{bar.datetime}\tlong_stop={self.long_stop}\tintra_trade_high={self.intra_trade_high}'
                  f'\tatr={self.atr_value}')

        elif self.pos < 0:
            self.intra_trade_high = bar.high_price
            self.intra_trade_low = min(self.intra_trade_low, bar.low_price)

            self.short_stop = self.intra_trade_low + self.atr_value * self.sl_multiplier
            self.cover(self.short_stop, abs(self.pos), True)
            print(f'--平空：{bar.datetime}\tshort_stop={self.short_stop}\tintra_trade_low={self.intra_trade_low}'
                  f'\tatr={self.atr_value}')

        self.put_event()

    def on_order(self, order: OrderData) -> None:
        """
        Callback of new order data update.
        """
        pass

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
