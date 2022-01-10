"""Trade crypto based on streaming Tweets in real time."""

import argparse
from datetime import datetime, timedelta
import pytz
import time
import tweepy

from APIs import APIClients
import Trade


class TradeDataForKilledStream():
    def __init__(self):
        self.side = "buy"
        self.buy_time = None
        self.text = ""

    def save_buy_order_data(self, buy_time, text):
        self.side = "sell"
        self.buy_time = buy_time
        self.text = text


class StreamListener(tweepy.StreamListener):
    def __init__(self, twitter_api=None, binance_api=None, username=None,
                 ticker=None, amount_to_trade_usd=None,
                 trade_data_for_stream_kill=None,
                 sell_time=None):
        self.api = twitter_api
        self.username = username
        self.ticker = ticker
        self.ticker_str = ticker[:-3].lower()
        self.amount_to_trade_usd = amount_to_trade_usd
        self.insufficient_funds = False
        self.binance_trader = Trade.BinanceTrading(binance_api)
        self.trade_data_for_stream_kill = trade_data_for_stream_kill
        self.sell_time = sell_time
        self.executed_qty = 0

    def on_status(self, status):
        if self.trade_data_for_stream_kill.side == "buy":
            if status.user.screen_name.lower() != self.username:
                return
            if not self.from_creator(status):
                return

            if hasattr(status, "extended_tweet"):
                text = status.extended_tweet['full_text']
            else:
                text = status.text

            if not (self.ticker_str in text.lower()):
                return

            buy_order = self.create_order('buy')
            print("Buy order placed")
            if self.insufficient_funds:
                return
            if buy_order:
                buy_time = datetime.fromtimestamp(
                    float(buy_order['transactTime']) / 1000).astimezone(
                        pytz.timezone('UTC'))
                self.executed_qty = float(buy_order['executedQty'])
                print("Buy order filled")
            else:
                buy_time = datetime.now(pytz.timezone('UTC'))
            self.trade_data_for_stream_kill.save_buy_order_data(buy_time, text)
            self.trade_data_for_stream_kill.side = "sell"

        if self.trade_data_for_stream_kill.side == "sell":
            while True:
                now = datetime.now(pytz.timezone('UTC'))
                if now - self.trade_data_for_stream_kill.buy_time > timedelta(
                        hours=self.sell_time):
                    self.trade_data_for_stream_kill.side = "buy"
                    sell_order = self.create_order('sell')
                    if self.insufficient_funds:
                        return
                    if sell_order:
                        print("Sell order placed")
                        sell_time = datetime.fromtimestamp(
                            float(
                                sell_order['transactTime']) / 1000).astimezone(
                            pytz.timezone('UTC'))
                        print("Sell order filled")

                    break
                time.sleep(1)

    def on_error(self, status):
        """Tweepy error."""
        return

    def from_creator(self, status):
        """Check to ensure the correct user Tweeted."""
        if hasattr(status, 'retweeted_status'):
            return False
        elif status.in_reply_to_status_id:
            return False
        elif status.in_reply_to_screen_name:
            return False
        elif status.in_reply_to_user_id:
            return False
        return True

    def create_order(self, side):
        """Create the trade order on Binance.us."""

        prices = self.binance_trader.check_balances()
        amount_of_bnb_usd = float(prices['BNB']['USD invested'])
        amount_of_usd = float(prices['USD']['amount'])

        # create buy orders
        if side.lower() == "buy":
            trans_fee = self.amount_to_trade_usd * 0.001
            if (amount_of_usd < self.amount_to_trade_usd or
                   (amount_of_usd - self.amount_to_trade_usd < trans_fee and amount_of_bnb_usd < trans_fee)):
                msg = 'Not enough USD to buy.'
                msg += ' Balance: {} USD,'.format(prices['USD']['amount'])
                msg += ' Buy request: {} USD.'.format(self.amount_to_trade_usd)
                print(msg)
                self.insufficient_funds = True
                return
            order = self.binance_trader.create_buy_order(self.ticker,
                                                         self.amount_to_trade_usd,
                                                         side='BUY',
                                                         type="MARKET")

        # create sell orders
        elif side.lower() == "sell":
            price_per_ticker_coin = float(
                prices[self.ticker[:-3]]['price per coin (USD)'])
            amount_of_ticker_coin = float(
                prices[self.ticker[:-3]]['amount'])
            amount_to_sell = price_per_ticker_coin * self.executed_qty
            trans_fee = self.amount_to_trade_usd * 0.001
            if amount_of_ticker_coin < self.executed_qty:
                msg = 'Not enough {} to sell.'.format(self.ticker)
                msg += ' Balance: {} - {},'.format(self.ticker[:-3], amount_of_ticker_coin)
                msg += ' Sell request: {} - {}.'.format(self.ticker[:-3], amount_to_sell)
                print(msg)
                self.insufficient_funds = True
                return
            elif amount_to_sell < 10:
                msg = 'Sell size was < 10 USD. Sell size - '
                msg += ' {} USD.'.format(amount_to_sell)
                print(msg)
                self.insufficient_funds = True
                return
            elif amount_of_usd < trans_fee and amount_of_bnb_usd < trans_fee:
                msg = 'Not enough USD or BNB to cover transaction fee for selling.'
                msg += ' Balance: USD - {},'.format(amount_of_usd)
                msg += ' Balance: BNB {},'.format(amount_of_bnb_usd)
                msg += ' Transaction fee: USD - {}.'.format(trans_fee)
                print(msg)
                self.insufficient_funds = True
                return
            order = self.binance_trader.create_sell_order(self.ticker,
                                                          self.executed_qty,
                                                          side='SELL',
                                                          type="MARKET")
        else:
            raise ValueError("Incorrect side. Must be either 'buy' or 'sell'.")

        self.insufficient_funds = False
        return order


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument('-u', '--username', type=str, required=True,
                        help="Twitter username of person you want to track.")
    parser.add_argument('-t', '--ticker', type=str, required=True,
                        help="Cryptocurrency ticker -for tracking on Binance.us.")
    parser.add_argument('-d', '--amount_to_trade_usd', type=float, required=True,
                        default=10, help="Amount of money in USD that you want to trade.")
    parser.add_argument('-s', '--sell_time', type=float, required=True,
                        help="Time in hours after the Tweet that you want to sell.")
    parser.add_argument('-twitter_api', '--twitter_api_keys_file', type=str,
                        required=True, help="Path to file with Twitter API keys.")
    parser.add_argument('-binance_api', '--binance_us_api_keys_file', type=str,
                        required=True, help="Path to file with Binance.us API keys.")

    args = parser.parse_args()

    # set up inputs
    username = args.username
    ticker = args.ticker
    amount_to_trade_usd = args.amount_to_trade_usd
    sell_time = args.sell_time

    twitter_api_keys_file = args.twitter_api_keys_file
    binance_us_api_keys_file = args.binance_us_api_keys_file

    trade_data_for_stream_kill = TradeDataForKilledStream()

    while True:
        try:
            print("setting up Twitter stream...")

            # set up apis
            apis = APIClients()
            apis.set_up_apis(binance_us_api_keys_file=binance_us_api_keys_file,
                             twitter_api_keys_file=twitter_api_keys_file)
            api_clients = apis.clients

            binance_api = api_clients['Binance.us Client']
            twitter_api = api_clients['Twitter Client']

            user = twitter_api.get_user(username)

            # fetching the ID
            user_id = user.id_str

            # listen to tweets and make trades, filtering on usernames and keywords
            tweets_listener = StreamListener(twitter_api=twitter_api,
                                             binance_api=binance_api,
                                             username=username,
                                             ticker=ticker,
                                             amount_to_trade_usd=amount_to_trade_usd,
                                             trade_data_for_stream_kill=trade_data_for_stream_kill,
                                             sell_time=sell_time)
            stream = tweepy.Stream(twitter_api.auth, tweets_listener)
            stream.filter(follow=[user_id])
        except Exception as e:
            print(e)
            time.sleep(5)
            continue
