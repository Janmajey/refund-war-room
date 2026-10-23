import argparse
import json

from war_room.config import FAULT_RATE
from war_room.setup import build_agent


def main():
    parser = argparse.ArgumentParser(description="Ask the refund war room agent a question.")
    parser.add_argument("question")
    parser.add_argument("--no-verify", action="store_true")
    parser.add_argument("--faults", type=float, default=FAULT_RATE)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--full", action="store_true", help="include tool calls and the state trace")
    args = parser.parse_args()

    agent, _ = build_agent(verify=not args.no_verify, fault_rate=args.faults, seed=args.seed)
    out = agent.ask(args.question)
    if not args.full:
        out = {k: v for k, v in out.items() if k not in ("calls", "trace")}
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
