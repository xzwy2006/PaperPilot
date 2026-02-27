"""
paperpilot.core.dedup
~~~~~~~~~~~~~~~~~~~~~
Deduplication module for PaperPilot.

Public API
----------
run_dedup(records)  →  list[DedupCluster]
"""
from .matching import DedupCluster, cluster_records


def run_dedup(records: list[dict]) -> list[DedupCluster]:
    """
    Detect and cluster duplicate records.

    Args:
        records: List of record dicts.  Each dict must have an ``"id"`` key.
                 The following optional fields are used for matching:

                 - ``title_norm``  (str)  pre-normalised title
                 - ``year``        (int | str)
                 - ``authors``     (str | list[str])
                 - ``doi``         (str)
                 - ``pmid``        (str | int)
                 - ``cnki_id``     (str)
                 - ``abstract``    (str)   — used only for canonical scoring

    Returns:
        List of :class:`DedupCluster`.  Only clusters with two or more
        members are returned; singletons (unique records) are omitted.

    Example::

        from paperpilot.core.dedup import run_dedup

        clusters = run_dedup(my_records)
        for cluster in clusters:
            print(cluster.canonical_record_id, cluster.member_ids)
    """
    return cluster_records(records)


__all__ = ["DedupCluster", "run_dedup"]
