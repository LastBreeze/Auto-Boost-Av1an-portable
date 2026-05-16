# vs-engine
# Copyright (C) 2022  cid-chan
# This project is licensed under the EUPL-1.2
# SPDX-License-Identifier: EUPL-1.2
"""
vsengine - A common set of function that bridge vapoursynth with your application.

Parts:
- video:   Get frames or render the video. Sans-IO and memory safe.
- vpy:     Run .vpy-scripts in your application.
- policy:  Create new isolated cores as needed.
- loops:   Integrate vsengine with your event-loop (be it GUI-based or IO-based).
"""
