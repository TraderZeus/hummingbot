#!/bin/bash

# Start Hyperliquid BTC-USDT Market Making Bot
# This script activates the Hummingbot environment and starts the market making bot

# Change to the Hummingbot directory
cd "$(dirname "$0")"

# Check if the conda environment is activated
if [[ $CONDA_DEFAULT_ENV != "hummingbot" ]]; then
    echo "Activating Hummingbot conda environment..."
    
    # Find conda executable
    CONDA_EXE=$((find /opt/conda/bin/conda || find ~/anaconda3/bin/conda || \
        find /usr/local/anaconda3/bin/conda || find ~/miniconda3/bin/conda || \
        find /root/miniconda/bin/conda || find ~/Anaconda3/Scripts/conda || \
        find $CONDA/bin/conda) 2>/dev/null)
    
    if [ "${CONDA_EXE}_" == "_" ]; then
        echo "Error: Could not find conda. Please make sure Anaconda/Miniconda is installed."
        exit 1
    fi
    
    CONDA_BIN=$(dirname ${CONDA_EXE})
    source "${CONDA_BIN}/activate" hummingbot
fi

# Start Hummingbot with the Hyperliquid market making strategy
echo "Starting Hummingbot with Hyperliquid BTC-USDT market making strategy..."
./start -f scripts/hyperliquid_btc_market_maker.py -c conf/strategies/hyperliquid_btc_market_maker.yml

# Note: This will open the Hummingbot interface
# You can then type 'start' to begin the strategy