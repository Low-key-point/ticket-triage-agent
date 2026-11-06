import argparse
import json
from .agent import Agent


def main():
    parser = argparse.ArgumentParser(description="中文银行咨询分流演示")
    parser.add_argument("text", help="中文银行咨询")
    parser.add_argument("--id", dest="ticket_id")
    args = parser.parse_args()
    print(json.dumps(Agent().submit(args.text, args.ticket_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
