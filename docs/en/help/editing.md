# Edit Markdown, tables and formulas

## Your goal

Write on the formatted page and switch to Markdown source when needed.

## Before you start

Connect a local folder first. Practise in the demo vault if you prefer.

## Steps

Type `/` at the start of a line or after a space to insert headings, lists, tasks, quotes, tables, code, images, links, equations or Mermaid diagrams. The menu includes icons, descriptions, categories and recently used items. Search by name or aliases such as `/h2` and `/todo`; use the arrow keys and Enter, or Esc to keep the literal text. Code, formulas, properties and URLs do not open the menu.

Select text for the formatting toolbar. `Ctrl/⌘+B`, `Ctrl/⌘+I` and `Ctrl/⌘+E` toggle bold, italic and inline code. Paste a URL over selected text to make a link, or use `Ctrl/⌘+Shift+K` to enter one. Type `[[` and a note name to choose a note by its full path.

Hover beside a block to insert with **+**, or use its handle to convert, duplicate, move or delete it. Drag the handle to reorder paragraphs, list items or whole blocks. Select text across paragraphs and type directly in table cells. Tab moves between cells and adds a row from the last cell; the table toolbar manages rows, columns, the header and alignment. Paste screenshots or drop files into the editor: attachments go in the vault's central `_attachments` folder (or configured `attachment_folder`) with unique names. Uploading does not replace existing files; undoing the inserted link keeps the uploaded file. Failed or cancelled uploads may leave completed files in that folder.

Files remain ordinary Markdown; unchanged blocks and document properties retain their original source. The page and source views share undo history. Equations and Mermaid stay rendered and have dedicated editing panels. Complex or unsupported content is preserved for display and can be located in source. Changing the interface language keeps the editor and its history. Tables use simple Markdown structures, without merged cells or nested blocks inside cells.

**On this page** shows the current Markdown note’s headings in a borderless outline to the left of the text. Click the double chevron at its upper left to collapse it; a list icon stays in the same place to expand it again. For headings with subsections, clicking the heading text both folds or unfolds its subtree and navigates to the section. The arrow toggles folding only; headings without subsections simply navigate. Nested folding is retained while editing or hiding the outline. Reading a hidden subsection highlights its collapsed ancestor without reopening it. The current section is blue and follows document scrolling; click a heading to jump near the top of the page or source view. The outline updates while you edit, includes underlined headings and keeps repeated headings separate. Code blocks and frontmatter are excluded. Each note’s open/closed choice is remembered for the current session. Narrow document panes start collapsed; expanding shows an overlay that stays open when toggling a parent heading and closes after choosing a heading without subsections or pressing Esc.

## What to expect

Ordinary edits autosave. Rich text and source share undo history.

## If it does not work

Inspect complex structures in source. AI drafts pause autosave and require an explicit save.

## Next steps

- [Highlight text and discuss notes](annotations.md)
- [Review AI changes and save a draft](ai-drafts.md)
