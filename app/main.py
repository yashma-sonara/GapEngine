import json
import argparse
from pipeline.analysis import GapAnalysis
from config import DEFAULT_SOURCES


def main():
    parser = argparse.ArgumentParser(description="Gap Score — marketing claims vs reality")
    parser.add_argument("--subject", required=True, help="e.g. 'Disney Cruise Line'")
    parser.add_argument("--claim", required=True, help="e.g. 'Is it worth the price?'")
    parser.add_argument(
        "--category",
        required=True,
        choices=list(DEFAULT_SOURCES.keys()),
        help="Category to analyse",
    )
    parser.add_argument("--output", help="Optional path to save JSON result")
    args = parser.parse_args()

    analysis = GapAnalysis()
    result = analysis.run(args.subject, args.claim, args.category)
    output = result.to_dict()

    print("\n" + "=" * 60)
    print(f"GAP SCORE: {output['gap_score']} / 10")
    print(f"CONFIDENCE: {output['confidence']}")
    print(f"VERDICT: {output['verdict']}")
    print("=" * 60 + "\n")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Full result saved to {args.output}")
    else:
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()