# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

delegated: Django, PostgreSQL, and Docker Compose for deployment to Debian.

## Users

- Administrators manage all classes, teacher accounts, permissions, students, submissions, and published boards.
- Teachers submit praise for their assigned subjects and classes. A homeroom teacher is also a subject teacher and receives additional permissions for their assigned class.

## Product Purpose

The site collects daily class praise from subject teachers. Homeroom teachers review and publish the final board as PNG images for manual sharing with class groups.

## Operating Context

Teachers use phones or computers. Subject teachers report praise for the current day. Homeroom teachers manage students, review submissions, finalize boards, and download images.

## Capabilities and Constraints

- The site supports multiple classes and teacher accounts with multiple class and subject assignments.
- The teacher login list shows identities in `subject-name` format. Administrators use a separate, unlisted login route.
- New accounts start with password `123456` and must change it on first login. Teachers can change their own passwords. Only administrators can force-reset teacher passwords. A reset password does not trigger another forced change.
- Subject teachers can create multiple praise items per day, select individual students or the whole class, and edit submitted items until the board is finalized.
- Homeroom teachers can manage their assigned class roster, adjust submissions, finalize a daily board, and reopen it for corrections.
- Administrators can manage all product data and permissions.
- Roster import accepts XLSX and CSV files with preview and validation. Student numbers identify students within a class. Historical boards preserve submitted names and whole-class roster snapshots.
- Final boards use Chinese PNG templates, display subject sections, and paginate long content. The site does not send images to class groups.
- The site does not provide public registration, parent access, missing-submission reminders, or ranking.
- The application uses `Asia/Shanghai` for daily reporting. It runs on Debian with Docker Compose, PostgreSQL, and Caddy.

## Evidence on Hand

No existing brand assets, class rosters, or production data were supplied. Do not invent real school or student information.

## Product Principles

- Keep teacher reporting fast on mobile and complete on desktop.
- Enforce class and subject permissions on the server.
- Preserve finalized historical records.
- Make the final board easy to review and share as an image.
