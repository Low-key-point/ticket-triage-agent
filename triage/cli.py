import argparse
import json
from .agent import Agent


def main():
    parser = argparse.ArgumentParser(description="Local BANKING77 triage demo")
    parser.add_argument("text", help="English banking request")
    parser.add_argument("--id", dest="ticket_id")
    args = parser.parse_args()
    print(json.dumps(Agent().submit(args.text, args.ticket_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
