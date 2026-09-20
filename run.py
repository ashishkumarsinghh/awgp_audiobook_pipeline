#!/usr/bin/env python3
"""AWGP Audiobook Pipeline - Minimal verbosity root runner.

Usage from root folder:
    python run.py <book_name> <stage>

Stages:
    0 or ocr          Stage 0: Extract text from PDF into 00_ocr/ocr_raw.txt
    1 or segment      Stage 1: Segment text from 00_ocr/ into 01_segments/segments.json
    2 or phonetics    Stage 2: Apply phonetics & prosody to 02_phonetics/phonetics.json
    3 or audio        Stage 3: Synthesize chunks from 02_phonetics/ into 03_audio/
    4 or master       Stage 4: Master audio chunks into 04_master/
    5 or speed        Stage 5: Speed & flow tempo optimization (default 1.15x)
    6 or metadata     Stage 6: ID3 metadata tagging & export as <pdf_name>.mp3
    all               Run all stages sequentially

To inspect current progress:
    python run.py <book_name>
"""
import sys
from src.pipeline_v3 import main

if __name__ == "__main__":
    main()
