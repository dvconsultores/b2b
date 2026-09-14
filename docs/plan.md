# Cold Email Outreach Plan for "Nomina Atenea"

## 1. Core Philosophy

Don't try to sell in the first email. Try to start a human conversation.

Your list is large and messy. The biggest problems are not design — they are **deliverability** and **relevance**. Most people won't read your email. So the goal of email #1 is simply to get a reply.

---

## 2. Why "Less Is More"

Two reasons:

**Deliverability.** Plain-text emails land in the inbox. HTML emails with images, logos, and links get flagged as bulk marketing by Gmail and Outlook. In cold outreach, a first email with images can multiply your bounce rate massively. A plain email looks like a real person wrote it.

**Behavior.** Business owners get dozens of vendor emails a day. They ignore anything that looks like a newsletter or ad. A short, personal, text-only email gets far more replies than a designed one. Images and fancy buttons get skipped by reflex.

So the rule is: **no image, no link, no attachment in the first email.**

---

## 3. The Three-Step Flow

### Step 1 — First Email: The Hook

- Format: plain text only. No image, no link, no attachment, no big signature.
- Tone: personal, short, like a message from a phone.
- Content: mention their company name and city. State the problem you solve (manual payroll, wasted time, errors).
- Goal: get a reply. Not a sale. Not a demo. Just a "yes, tell me more."

The call to action is a simple question, not a button.

### Step 2 — After They Reply: Send the Link

- Only after they show interest, send a second email with a link to your landing page.
- No attachments. A link is safer than a PDF or image for spam filters.
- This is where the prospect enters your funnel properly.

### Step 3 — Landing Page: The Real CTA

This is where the image, the price, and the demo button live.

- Keep it simple. One field: number of employees.
- One button: "Calculate my price."
- After they submit, show an estimated price and a "Book a 15-minute demo" button.
- Now the prospect is qualified, and you know they're interested.

---

## 4. Summary Table

| Stage | What to Send | Goal |
| :--- | :--- | :--- |
| First Email | Plain text, one question | Get a reply |
| Reply | Link to landing page | Move them to your site |
| Landing Page | Form: number of employees | Qualify and show price |
| Final CTA | "Book Demo" button | Close the meeting |

Image, price table, and demo CTA all belong on the landing page, never in email #1.

---

## 5. Warning About Your List and Amazon SES

Your list has two types of emails:

- **Personal emails** (firstname.lastname@company.com) — more likely to be read.
- **Generic emails** (info@, ventas@, contacto@) — more likely to bounce or be ignored.

If your bounce rate goes above 2%, Amazon SES will suspend your account. So:

- Start with personal emails only.
- Remove invalid, empty, or obviously generic addresses.
- Verify the list before sending anything.
- Never send to the whole list at once.

Better to send 100 real emails than 1,000 to junk inboxes.

---

## 6. Generic Software Plan (Concept Only)

You want a small Python tool, but the idea is generic and applies to any language. Here is what the tool should do, in plain terms.

### Part A — Data Loading
Read both Excel files. The first file has company, RIF, email, city, and area. The second file has multiple sheets with company, contact name, email, and city. Combine everything into one list of records.

### Part B — Cleaning
Normalize every email: lowercase, remove spaces, validate format. Drop rows with missing or broken emails. Normalize city names. Fix obvious typos.

### Part C — Deduplication
The same company or email may appear in both files. Remove duplicates. Keep the most complete record.

### Part D — Classification
Split emails into two groups: personal and generic. Personal emails get priority. Generic emails go to a second, slower campaign or get skipped entirely at first.

### Part E — Sending
Connect to Amazon SES. Send plain-text emails only. Throttle the sending speed — a few per minute, not thousands at once. Stop immediately if bounce rate climbs. Never send the same email twice.

### Part F — Tracking
Keep a simple local log (a file or small database) with: email, company, date sent, status (sent, bounced, replied, unsubscribed). Check this log before every send. This prevents duplicates and lets you measure reply rate.

### Part G — Safety Rules Built In
- No HTML in email #1.
- No attachments ever.
- No more than N emails per hour.
- Honor any unsubscribe reply immediately.
- Pause the campaign automatically if bounces spike.

### Part H — Build Order
1. Load and clean the data. Produce one clean file.
2. Classify into personal vs generic.
3. Build the tracker first, before sending anything.
4. Run a dry run: print emails to screen, send nothing.
5. Send a few test emails to yourself and trusted addresses.
6. Move to production SES with strict throttling.
7. Track replies manually at first. Automate later.

---

## 7. Final Takeaway

- The first email is a conversation starter, not a sales pitch.
- Plain text beats design in cold outreach.
- The image, price, and demo CTA all live on the landing page.
- Protect your SES reputation above all else.
- Quality of list beats quantity of emails.

If you follow this, you'll get fewer bounces, higher reply rates, and a cleaner funnel — even though most people won't read your first email. The ones who do will be the right ones.