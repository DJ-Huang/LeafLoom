# Work with tasks, data views and queries

## Your goal

Display notes with properties as tables, tasks or calendars.

## Before you start

Try the demo’s sample views with fictional tasks first.

## Steps

1. Use consistent properties such as `status`, `priority` and `due`.
2. Open a `.base` file and switch its configured views. Supported configurations render tables, task lists, kanban or calendars.
3. Edit writable table properties or task status; changes save to the original note.
4. `file.*` and formula fields are read-only. Property queries use the limited TABLE/LIST grammar, without arbitrary execution.

## What to expect

Views present existing notes. Moving tasks or editing properties changes their source files.

## If it does not work

This supports a bounded grammar and view set, not the entire Dataview or TaskNotes plugin environment. Inspect fields and configuration if a view fails.

## Next steps

- [Use templates, daily notes and properties](templates-properties.md)
- [Restore note history and recycled files](recovery.md)
