---
name: ticket
description: Fetch a NICOS ticket from the issue tracker
---

## When to use

Use me when you need to know what a NICOS ticket contains.

## How it works

- NICOS tickets (also called issues) are stored in a Redmine instance at https://forge.frm2.tum.de/redmine
- To check a certain ticket, fetch the URL `https://forge.frm2.tum.de/redmine/issues/<NUMBER>`
- It will have metadata (status, target version, assignee), body content and comments.
