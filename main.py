"""CLI: print a weather forecast summary for a place and date."""

import argparse
import datetime as dt

from forecast import (
    DateOutOfRangeError,
    LocationNotFoundError,
    get_weather_summary,
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--location",
        required=True,
        help='Place name, e.g. "Manchester, UK"',
    )
    parser.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="Date to forecast, as YYYY-MM-DD (default: today)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        print(get_weather_summary(args.location, args.date))
    except (LocationNotFoundError, DateOutOfRangeError, ValueError) as error:
        raise SystemExit(f"Error: {error}")


if __name__ == "__main__":
    main()
