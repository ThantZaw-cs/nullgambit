# Public, self-contained test inputs

`python -m unittest discover -s tests -v` does not read `data/online/`.

- `test_history_ordering.py` embeds the single development FEN needed to reproduce
  the round-54 fork regression. Its halfmove clock is zero following a capture;
  there is no omitted reversible history affecting this search. The test uses
  our frozen v3 and v4 sources, not an external engine or downloaded analysis.
- `test_online_review.py` builds a minimal synthetic PGN in a temporary directory:
  a nonstandard initial FEN and a two-cycle knight repetition. It covers missing
  logs/version attribution and duplicate/conflicting exports without private files.
- `tools/positions.py` and `benchmarks/astra-v4/validation-openings.json` contain
  the public opening inputs. The release smoke check reuses the first already
  evaluated opening with colors swapped; it is not an unseen strength test.
- `test_v4_package.py` builds a temporary archive, checks exact candidate bytes,
  and verifies that substituting the root legacy implementation is rejected.

The raw online PGN/LOG/CSV/ZIP files remain local and ignored. Developer analysis
commands such as `tools.online_review` intentionally require those files; they
are not prerequisites for the tests or the release workflow.
