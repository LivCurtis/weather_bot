"""CLI: print a weather forecast, or the best day this week for an activity."""

import argparse
import datetime as dt

from forecast import (
    ACTIVITIES,
    DateOutOfRangeError,
    LocationNotFoundError,
    get_best_day_summary,
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
        help="Date to forecast, as YYYY-MM-DD (default: today). "
        "Ignored if --activity is set.",
    )
    parser.add_argument(
        "--activity",
        choices=sorted(ACTIVITIES),
        help="If set, recommend the best day for this activity instead of "
        "forecasting a single date.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days ahead to consider with --activity (default: 7).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        if args.activity:
            summary = get_best_day_summary(
                args.location, args.activity, args.days
            )
            print(summary)
        else:
            print(get_weather_summary(args.location, args.date))
    except (LocationNotFoundError, DateOutOfRangeError, ValueError) as error:
        raise SystemExit(f"Error: {error}")


if __name__ == "__main__":
    main()
