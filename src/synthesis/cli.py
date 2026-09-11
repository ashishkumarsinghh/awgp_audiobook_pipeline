import argparse
import sys
import json
from src.synthesis.parser.xml_parser import XMLParser
from src.synthesis.models.config import SynthesisConfig
from src.synthesis.speech.planner import SpeechPlanner
from src.synthesis.engine.chunker import SemanticChunker
from src.synthesis.ssml.providers.edge import EdgeTTSRenderer

def validate(args):
    with open(args.input, 'r', encoding='utf-8') as f:
        doc = XMLParser.parse(f.read())
    print(f"Validated {len(doc.blocks)} semantic blocks.")

def generate_ssml(args):
    with open(args.input, 'r', encoding='utf-8') as f:
        doc = XMLParser.parse(f.read())
    planner = SpeechPlanner(SynthesisConfig())
    plan = planner.plan(doc)
    renderer = EdgeTTSRenderer()
    ssml = renderer.render(plan)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(ssml)
    else:
        print(ssml)
    print("SSML Generated successfully.")

def main():
    parser = argparse.ArgumentParser(prog='audiobook')
    subparsers = parser.add_subparsers(dest='command', required=True)
    
    val_p = subparsers.add_parser('validate')
    val_p.add_argument('input')
    
    gen_p = subparsers.add_parser('generate-ssml')
    gen_p.add_argument('input')
    gen_p.add_argument('--output', '-o')
    
    args = parser.parse_args()
    if args.command == 'validate':
        validate(args)
    elif args.command == 'generate-ssml':
        generate_ssml(args)

if __name__ == '__main__':
    main()
