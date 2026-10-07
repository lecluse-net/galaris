"""Opt-in CLI options for an isolated real-engine benchmark campaign."""


def pytest_addoption(parser):
    group = parser.getgroup("memory-benchmark")
    group.addoption("--memory-benchmark-corpus", default="", help="Synthetic corpus directory")
    group.addoption("--memory-benchmark-output", default="", help="New artifacts directory")
    group.addoption("--memory-benchmark-reference", default="", help="Frozen algorithm sources under artifacts, for previous variant")
    group.addoption("--memory-benchmark-worlds", type=int, default=4, help="World limit; 0 means all")
    group.addoption("--memory-benchmark-profile-sample", action="store_true", help="One rotating calendar regime per profile")
    group.addoption("--memory-benchmark-workers", type=int, default=4, help="Isolated concurrent worlds")
    group.addoption("--memory-benchmark-shards", type=int, default=1, help="Independent database partitions")
    group.addoption("--memory-benchmark-shard", type=int, default=0, help="Zero-based database partition")
    group.addoption("--memory-benchmark-variants", default="baseline,relevance_first,history,entities,time,combined")
