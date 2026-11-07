# 0269 — Private Goal categories

Date: 2026-11-07
Status: Accepted

## Decision

`app.goal` owns a personal category nomenclature in `goal_categories`. A Goal has zero
or one category through the nullable `goals.category_id` foreign key. Categories use
`HistoryMixin` for creator and modification audit and logical deletion.

Only the authenticated category creator can list, rename, delete or assign a category.
Global Agent management does not bypass this ownership. Categorization grants no Goal
access. A manager reading another creator's classified Goal receives no category identifier;
an unrelated Goal edit preserves that hidden classification. Shared Goal WebSocket events
omit category identifiers; authorized HTTP reads refresh personal classifications.

Deleting a category detaches its Goals without deleting them, advances their revisions and
retains the category's audit record. Assignments and deletion lock the category before
the Goal, preventing a newly committed link to a category being removed concurrently.

The Goals UI owns the nomenclature manager and optional classification selector, alongside
category and uncategorized filters. The list reuses the standard authenticated AgentAvatar.
Category labels appear as section headings. Category ordering is always alphabetical,
with unclassified Goals last; column sorting is secondary within a category. The server
applies this order before pagination and treats hidden categories as unclassified.

Descendants always inherit their visible root's category for listing, filtering and sorting,
including an uncategorized root. `GoalListRead.effective_category_id` exposes that classification;
`category_id` retains each Goal's own private value for editing and detachment. A recursive
projection applies inheritance and parent-first ordering before filters and pagination.
Column sorting orders roots and siblings without interleaving branches. Hidden ancestors
never grant access or expose their classification; their visible descendants are unclassified.

## Verification

Synthetic HTTP and PostgreSQL tests cover ownership between global managers, denied
operations, assignment, removal, filtering, event confidentiality and logical deletion.
Browser journeys cover category creation, renaming, Goal editing and reopening, filtering,
non-destructive category deletion and retained input after a temporary error.
The regression scenarios include three levels with conflicting own categories, uncategorized
roots, restricted scopes, reclassification, detachment and ascending/descending Agent sorting
across page boundaries. Earlier category coverage used independent roots and missed this interaction.
