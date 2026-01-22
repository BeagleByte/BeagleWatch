#!/bin/bash

# Start RSS processor in background
# Adjust path if CyberSecFeeds.py is in a subdirectory
python app/CyberSecFeeds.py &

# Set Flask app location and start Flask
export FLASK_APP=app/web/news_feeder.py
python -m flask run --host=0.0.0.0 --port=5000