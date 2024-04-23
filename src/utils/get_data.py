import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import numpy as np
from plotly.subplots import make_subplots
import os
from jinja2 import Environment, FileSystemLoader
import json
import markdown2
from IPython.display import HTML
import plotly
import configparser
from src.utils.configparser import remove_comments_and_convert
from src.utils.logger import get_logger

def get_previous_date(date):
    ## considering the previous date could be last week friday, but if there is holiday, you should adjust this part manually
    # Convert the date string to a datetime object

    # Check if the given date is a Monday
    if date.weekday() == 0:  # Monday is represented by 0
        # If it's Monday, subtract 3 days to get the previous working day
        date_previous = date - timedelta(days=3)
    else:
        # If it's not Monday, subtract 1 day to get the previous working day
        date_previous = date - timedelta(days=1)

    return date_previous

def load_data(logger, date, ticker, date_previous, parameters_global):
    trade = pd.read_csv(f"{parameters_global['performace_data_path']}Performance_{date.strftime('%Y-%m-%d')}.csv")
    df = pd.read_csv(f"{parameters_global['future_data_path']}{ticker}/{ticker}_5min_data_{date.strftime('%Y-%m-%d')}.csv")
    try:
        df_previous = pd.read_csv(f"{parameters_global['future_data_path']}{ticker}/{ticker}_5min_data_{date_previous.strftime('%Y-%m-%d')}.csv")
    except FileNotFoundError as e:
        df_previous = df.copy()
        logger.info(f"Cannot find file '{e.filename}'")
    return trade, df, df_previous

def get_trade_rth(trade):

    ## Preprocess trade to trade_rth
    trade = trade.drop(columns=['symbol','_priceFormat', '_priceFormatType', '_tickSize', 'buyFillId','sellFillId'])
    # 1. Convert pnl to numeric format with proper handling of negative values
    trade['pnl'] = trade['pnl'].str.replace('$', '')
    trade['pnl'] = trade['pnl'].str.replace('(', '-').str.replace(')', '').astype(float)

    # 2. Convert boughtTimestamp and soldTimestamp to datetime format and adjust to UTC
    trade['boughtTimestamp'] = pd.to_datetime(trade['boughtTimestamp']) - pd.Timedelta(hours=7)
    trade['soldTimestamp'] = pd.to_datetime(trade['soldTimestamp']) - pd.Timedelta(hours=7)

    # 3. Convert duration to time format
    trade['duration'] = pd.to_timedelta(trade['duration'])

    #4. Filter out trades with boughtTimestamp or soldTimestamp between 9:30 and 16:10
    trade_rth = trade[(trade['boughtTimestamp'].dt.time >= pd.Timestamp('09:30').time()) &
                        (trade['boughtTimestamp'].dt.time <= pd.Timestamp('16:10').time()) |
                        (trade['soldTimestamp'].dt.time >= pd.Timestamp('09:30').time()) &
                        (trade['soldTimestamp'].dt.time <= pd.Timestamp('16:10').time())].copy()  # Ensure a copy of the DataFrame is created

    trade_rth['boughtTimestamp'] = trade_rth['boughtTimestamp'].dt.floor('min')
    trade_rth['soldTimestamp'] = trade_rth['soldTimestamp'].dt.floor('min')

    trade_rth['boughtTimestamp'] = trade_rth['boughtTimestamp'].dt.floor('5min')
    trade_rth['soldTimestamp'] = trade_rth['soldTimestamp'].dt.floor('5min')
    return trade_rth


def get_future_rth(df): 
    ## Preprocess TradingData(df) to df_rth

    # 0. Convert the 'Datetime' column to datetime dtype
    df['Datetime'] = pd.to_datetime(df['Datetime'])
    df.set_index('Datetime', inplace=True)

    # 1. Convert the 'Datetime' column to datetime if it's not already in datetime format
    df.index = pd.to_datetime(df.index)

    # 2. Filter rows within the specified time range directly using the index
    df_rth = df[(df.index.time >= pd.Timestamp('09:30').time()) & (df.index.time <= pd.Timestamp('16:10').time())]

    return df_rth

def get_pre_market(df_previous_rth): 
    pre_high = df_previous_rth['High'].max()
    pre_low = df_previous_rth['Low'].min()

    pre_open = df_previous_rth['Open'].iloc[0]
    pre_close = df_previous_rth['Close'].iloc[-1]

    return {
        'pre_high': pre_high,
        'pre_low': pre_low,
        'pre_open': pre_open,
        'pre_close': pre_close
    }

def get_ema(df_rth, df_previous_rth):
    # Copy the last 20 entries from the previous RTH DataFrame to ensure it's a separate DataFrame
    df_previous_rth = df_previous_rth[-20:].copy()

    # Combine previous and current trading session data into a new DataFrame
    combined_df = pd.concat([df_previous_rth, df_rth])

    # Calculate the 20-period EMA on the combined close prices and round to 2 decimal places
    combined_df['EMA_20'] = combined_df['Close'].ewm(span=20, adjust=False).mean().round(2)

    # Now, slice back out the EMA values that correspond only to df_rth dates
    # Ensure df_rth is also treated as a separate DataFrame if not already
    df_rth = df_rth.copy()
    df_rth.loc[:, 'EMA_20'] = combined_df['EMA_20'].iloc[-len(df_rth):].values

    return df_rth


def get_trades_sum(trade_rth):
    # Calculate winning and losing trades
    winning_trades = trade_rth[trade_rth['pnl'] > 0]
    losing_trades = trade_rth[trade_rth['pnl'] <= 0]

    # Data for pie chart
    return winning_trades, losing_trades

# Generate statistics for tables
def get_trade_stats(trades):
    if len(trades) == 0:
        return {'AveragePnL': 0, 'MaxPnL': 0, 'MinPnL': 0, 'TotalPnL': 0, 'Count': 0}
    return {
        'AveragePnL': round(trades['pnl'].mean(), 2),
        'MaxPnL': round(trades['pnl'].max(), 2),
        'MinPnL': round(trades['pnl'].min(), 2),
        'TotalPnL': round(trades['pnl'].sum(), 2),
        'Count': len(trades)
    }
