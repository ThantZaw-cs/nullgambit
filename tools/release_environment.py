"""Actual release-test host metadata, without claiming official container validation."""

from tools.validate_v4 import environment as base_environment


def environment() -> dict[str, object]:
    details = base_environment()
    details["scope"] = "Ordinary host compatibility and paired control; not official container"
    details["limitations"] = [
        "One selected CPU affinity and one numerical-library thread on Linux",
        "Formal run inherits the same 2 GiB address-space limit in both agent processes",
        "Address-space limit is not the official container memory cgroup",
        "No official EPYC hardware, read-only filesystem or network isolation",
        "Opponent suspension is not emulated; these frozen engines do not ponder",
        "Repeated regression positions do not establish playing strength",
    ]
    return details
