# TrailBot
A tool for automatically downloading images and video from trail cameras.

## Requirements
This tool relies on the Python [`gatt`](https://github.com/getsenic/gatt-python/) library for interfacing with cameras over bluetooth. This library currently only support Linux and requires BlueZ.

This tool also requires a bluetooth adapter that supports the LE protocol. This is a fairly common feature on modern bluetooth adapters. If you're after a recommendation for a cheap one that has been confirmed to work well on Linux, the TP-Link UB4A seems to work well.

## Supported Cameras
This tool should work on any camera that uses the app provided by "Shenzhen Xipiwuba Intelligent Technology". These cameras are sold under a variety of names and brands. The following cameras have been tested and confirmed to work with this tool:

* Toguard H85
