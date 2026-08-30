"""Repository-grouped train/test splitting to prevent leakage."""

from __future__ import annotations

from dataclasses import dataclass

from sklearn.model_selection import GroupShuffleSplit

from app.ml.datasets import DatasetRow


@dataclass(frozen=True, slots=True)
class GroupedSplit:
    train: tuple[DatasetRow, ...]
    test: tuple[DatasetRow, ...]

    @property
    def train_groups(self) -> frozenset[str]:
        return frozenset(row.repository_group for row in self.train)

    @property
    def test_groups(self) -> frozenset[str]:
        return frozenset(row.repository_group for row in self.test)


def grouped_train_test_split(
    rows: list[DatasetRow],
    *,
    test_size: float = 0.25,
    random_state: int = 42,
) -> GroupedSplit:
    """Split rows by repository group, never by individual row."""
    if len(rows) < 2:
        raise ValueError("At least two dataset rows are required")
    groups = [row.repository_group for row in rows]
    if len(set(groups)) < 2:
        raise ValueError("At least two repository groups are required")

    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
    train_idx, test_idx = next(splitter.split(rows, groups=groups))

    split = GroupedSplit(
        train=tuple(rows[int(index)] for index in train_idx),
        test=tuple(rows[int(index)] for index in test_idx),
    )
    if split.train_groups & split.test_groups:
        raise RuntimeError("Repository leakage detected in grouped split")
    return split
