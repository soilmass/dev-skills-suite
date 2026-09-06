"""Planted: subprocess without timeout."""
import subprocess

def run():
    return subprocess.run(["ls"], check=True)
