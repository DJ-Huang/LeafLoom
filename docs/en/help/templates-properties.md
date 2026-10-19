# Use templates, daily notes and properties

## Your goal

Reuse note structures and organize material with properties.

## Before you start

Prepare template and daily-note folders, relative to the vault root.

## Steps

1. Save their paths in **Settings → Templates and daily notes**.
2. Create a note from a template or open today’s daily note. Existing daily notes are retained.
3. Inspect and edit YAML properties, using source view when necessary.
4. Use consistent fields such as `status`, `tags` and `due`.

```yaml
---
title: Reading notes
tags: [reading]
status: open
---
```

## What to expect

Properties remain inside Markdown. Templates create new content; they do not keep old notes synchronized.

## If it does not work

Choose a new name for collisions. Keep field types consistent and preserve unknown properties.

## Next steps

- [Work with tasks, data views and queries](tasks-queries.md)
- [Edit Markdown, tables and formulas](editing.md)
- [Back up notes, comments and recovery data](backup.md)
