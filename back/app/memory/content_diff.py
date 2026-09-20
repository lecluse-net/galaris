"""Pure document revision comparison, independent of persistence and access control."""

import difflib
from .schemas import DocumentContentDiffHunk, DocumentContentDiffLine


_DOCUMENT_DIFF_MAX_CHARS = 2_000_000


def content_diff_hunks(
    previous: str,
    current: str,
) -> tuple[list[DocumentContentDiffHunk], int, int]:
    if len(previous) + len(current) > _DOCUMENT_DIFF_MAX_CHARS:
        raise ValueError("The selected document versions are too large to compare.")
    # Keep line endings so a missing or added final newline remains a visible,
    # restorable difference instead of being reported as identical content.
    before = previous.splitlines(keepends=True)
    after = current.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    hunks: list[DocumentContentDiffHunk] = []
    additions = 0
    deletions = 0
    for group in matcher.get_grouped_opcodes(n=3):
        first = group[0]
        last = group[-1]
        lines: list[DocumentContentDiffLine] = []
        for tag, old_start, old_end, new_start, new_end in group:
            if tag == "equal":
                for offset, text in enumerate(before[old_start:old_end]):
                    lines.append(
                        DocumentContentDiffLine(
                            kind="context",
                            text=text,
                            old_line=old_start + offset + 1,
                            new_line=new_start + offset + 1,
                        )
                    )
                continue
            if tag in {"delete", "replace"}:
                for offset, text in enumerate(before[old_start:old_end]):
                    deletions += 1
                    lines.append(
                        DocumentContentDiffLine(
                            kind="removed",
                            text=text,
                            old_line=old_start + offset + 1,
                        )
                    )
            if tag in {"insert", "replace"}:
                for offset, text in enumerate(after[new_start:new_end]):
                    additions += 1
                    lines.append(
                        DocumentContentDiffLine(
                            kind="added",
                            text=text,
                            new_line=new_start + offset + 1,
                        )
                    )
        hunks.append(
            DocumentContentDiffHunk(
                old_start=first[1] + 1,
                old_count=last[2] - first[1],
                new_start=first[3] + 1,
                new_count=last[4] - first[3],
                lines=lines,
            )
        )
    return hunks, additions, deletions
