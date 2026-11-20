import argparse
import json
import sys
from .agent import Agent


def configure_output():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main():
    configure_output()
    parser = argparse.ArgumentParser(description="银行客服工单分流智能体")
    parser.add_argument("text", help="银行客服咨询内容")
    parser.add_argument("--id", dest="ticket_id")
    args = parser.parse_args()
    print(json.dumps(Agent().submit(args.text, args.ticket_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
