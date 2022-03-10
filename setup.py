from importlib_metadata import entry_points
from setuptools import setup

setup(
  name="algopoker",
  version="1.0.0",
  install_requires=[
    "Flask",
    "Click",
    "flask_socketio",
    "socketio"
  ],
  entry_points = {
    'console_scripts': [
      'engine = cli:engine'
    ]
  }
)