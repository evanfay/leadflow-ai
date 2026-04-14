def seed_builtin_data(app, db):
    """Pre-load built-in sequences and templates. Idempotent."""
    with app.app_context():
        from models import Sequence, SequenceStep, Template, StepTemplate

        # ── Built-in Sequences ─────────────────────────────────────────────────
        if not Sequence.query.filter_by(is_builtin=True).first():

            # A-Account Cadence
            a_seq = Sequence(
                user_id=None,
                name='A-Account Cadence',
                description='Full 9-touch sequence for high-value (A-grade) accounts. Mix of email, LinkedIn, and phone over 21 days.',
                is_builtin=True,
            )
            db.session.add(a_seq)
            db.session.flush()

            a_steps = [
                (1,  'Email',    'observation',      True),
                (2,  'LinkedIn', 'linkedin_connect', False),
                (4,  'Email',    'hypothesis',       True),
                (7,  'Phone',    'voicemail',        False),
                (9,  'Email',    'proof',            True),
                (12, 'LinkedIn', 'linkedin_dm',      False),
                (15, 'Email',    'soft_close',       True),
                (18, 'Phone',    'live_call',        False),
                (21, 'Email',    'breakup',          True),
            ]
            for day, channel, slot, auto in a_steps:
                s = SequenceStep(sequence_id=a_seq.id, day_offset=day,
                                 channel=channel, template_slot=slot, is_auto=auto)
                db.session.add(s)

            # B-Account Cadence
            b_seq = Sequence(
                user_id=None,
                name='B-Account Cadence',
                description='Lighter 4-touch email-first sequence for B-grade accounts over 15 days.',
                is_builtin=True,
            )
            db.session.add(b_seq)
            db.session.flush()

            b_steps = [
                (1,  'Email',    'observation', True),
                (4,  'Email',    'hypothesis',  True),
                (9,  'Email',    'soft_close',  True),
                (15, 'LinkedIn', 'linkedin_dm', False),
            ]
            for day, channel, slot, auto in b_steps:
                s = SequenceStep(sequence_id=b_seq.id, day_offset=day,
                                 channel=channel, template_slot=slot, is_auto=auto)
                db.session.add(s)

            db.session.commit()

        # ── Built-in Templates ─────────────────────────────────────────────────
        if not Template.query.filter_by(is_builtin=True).first():
            builtin_templates = [
                # ── Core email touch types ─────────────────────────────────────
                {
                    'name': 'Opening Touch — Signal Observation',
                    'touch_type': 'observation',
                    'subject': 'quick question about {{company}}',
                    'body': (
                        'Hi {{first_name}},\n\n'
                        '{{signal_1}}\n\n'
                        "That caught my attention because it's the kind of thing that usually creates real friction "
                        "in customer communications — the back-and-forth that never quite gets resolved.\n\n"
                        "We build AI systems that handle that layer so your team doesn't have to. Happy to show you "
                        "what it looks like for a business like {{company}} on a quick call.\n\n"
                        '{{calendly_link}}\n\n'
                        'Best,'
                    ),
                },
                {
                    'name': 'Second Touch — Hypothesis',
                    'touch_type': 'hypothesis',
                    'subject': 'something I noticed about {{company}}',
                    'body': (
                        'Hi {{first_name}},\n\n'
                        "Following up from last week. I wanted to share a specific hypothesis about {{company}}.\n\n"
                        "Based on {{signal_1}}, my guess is your team is spending a meaningful chunk of time on "
                        "communication tasks that could run on autopilot — scheduling, follow-ups, status updates.\n\n"
                        "I could be wrong. But if I'm close, 15 minutes would probably be worth it to see what we've built.\n\n"
                        '{{calendly_link}}\n\n'
                        'Best,'
                    ),
                },
                {
                    'name': 'Third Touch — Proof / Case Study',
                    'touch_type': 'proof',
                    'subject': 'what we built for a {{company}} competitor',
                    'body': (
                        'Hi {{first_name}},\n\n'
                        "We recently finished a project for a company in your space. The short version: they were "
                        "losing customers in the gap between first inquiry and first response.\n\n"
                        "We automated that layer. Response times went from hours to seconds.\n\n"
                        "Not sure if {{company}} has the same challenge, but worth a 15-minute call to find out.\n\n"
                        '{{calendly_link}}\n\n'
                        'Best,'
                    ),
                },
                {
                    'name': 'Soft Close — Last Attempt Before Breakup',
                    'touch_type': 'soft_close',
                    'subject': 'still worth 15 minutes?',
                    'body': (
                        'Hi {{first_name}},\n\n'
                        "I've sent a few notes your way. Not trying to be persistent for its own sake — I just think "
                        "there's a real opportunity here for {{company}} and I haven't heard back.\n\n"
                        "If timing is off, totally fine. If you're curious what AI-driven communication automation "
                        "would look like for your operation, I'm still happy to show you.\n\n"
                        '{{calendly_link}}\n\n'
                        'Best,'
                    ),
                },
                {
                    'name': 'Breakup Email — Final Touch',
                    'touch_type': 'breakup',
                    'subject': 'closing the loop',
                    'body': (
                        'Hi {{first_name}},\n\n'
                        "Last note from me — I don't want to fill your inbox.\n\n"
                        "If the timing ever makes sense to look at what AI automation could do for {{company}}, "
                        "feel free to reach back out. Happy to help whenever it works.\n\n"
                        'Best,'
                    ),
                },
                # ── Trigger / follow-up templates ──────────────────────────────
                {
                    'name': 'Trigger — Link Clicked Follow-up',
                    'touch_type': 'link_clicked',
                    'subject': 'Re: quick question about {{company}}',
                    'body': (
                        'Hi {{first_name}},\n\n'
                        "Noticed you checked out our site — wanted to follow up while it's fresh.\n\n"
                        "Happy to walk you through exactly what we'd build for {{company}} on a short call. "
                        "No pitch, just a real conversation about whether it makes sense.\n\n"
                        '{{calendly_link}}\n\n'
                        'Best,'
                    ),
                },
                {
                    'name': 'Trigger — Reply Received Response',
                    'touch_type': 'reply_received',
                    'subject': 'Re: {{original_subject}}',
                    'body': (
                        'Hi {{first_name}},\n\n'
                        'Thanks for getting back to me.\n\n'
                        '{{suggested_reply}}\n\n'
                        'Best,'
                    ),
                },
                {
                    'name': 'Trigger — Out of Office Response',
                    'touch_type': 'out_of_office',
                    'subject': 'Re: quick question about {{company}}',
                    'body': (
                        'Hi {{first_name}},\n\n'
                        "Got your out-of-office. I'll follow up when you're back.\n\n"
                        'Best,'
                    ),
                },
                {
                    'name': 'Trigger — Not Now / Bad Timing Response',
                    'touch_type': 'not_now',
                    'subject': 'Re: quick question about {{company}}',
                    'body': (
                        'Hi {{first_name}},\n\n'
                        "Totally understand — timing matters. I'll check back in when things settle down.\n\n"
                        "If anything changes before then, feel free to reach out directly.\n\n"
                        'Best,'
                    ),
                },
                # ── LinkedIn templates ─────────────────────────────────────────
                {
                    'name': 'LinkedIn — Connection Request Note',
                    'touch_type': 'linkedin_connect',
                    'subject': '',
                    'body': (
                        'Hi {{first_name}}, I help companies like {{company}} automate customer communications. '
                        "Thought it might be worth connecting — I've been following what you're building."
                    ),
                },
                {
                    'name': 'LinkedIn — Direct Message Follow-up',
                    'touch_type': 'linkedin_dm',
                    'subject': '',
                    'body': (
                        'Hi {{first_name}},\n\n'
                        "Reached out via email a few times about {{company}} — wanted to try here in case email got buried.\n\n"
                        "We build AI systems that handle the customer communication layer most ops teams are drowning in. "
                        "Worth a 15-minute call if the timing's right.\n\n"
                        'Best,'
                    ),
                },
                # ── Phone templates ────────────────────────────────────────────
                {
                    'name': 'Phone — Voicemail Script',
                    'touch_type': 'voicemail',
                    'subject': '',
                    'body': (
                        "Hi {{first_name}}, this is [YOUR NAME] calling about {{company}}. "
                        "I've sent a couple of emails about AI communication automation — wanted to reach out directly. "
                        "Give me a call back at [YOUR NUMBER] or just reply to my email. Thanks."
                    ),
                },
                {
                    'name': 'Phone — Live Call Talk Track',
                    'touch_type': 'live_call',
                    'subject': '',
                    'body': (
                        "Opening: 'Hi, is this {{first_name}}? This is [YOUR NAME] — I've sent a few emails about {{company}}. "
                        "Do you have two minutes?'\n\n"
                        "Pitch: 'We build AI systems that automate the customer communication layer — scheduling, follow-ups, "
                        "status updates. Based on what I've seen with {{company}}, I think there's something real here. "
                        "Would a 15-minute call this week make sense to explore?'"
                    ),
                },
            ]

            for t in builtin_templates:
                template = Template(
                    user_id=None,
                    name=t['name'],
                    touch_type=t['touch_type'],
                    subject=t['subject'],
                    body=t['body'],
                    is_builtin=True,
                )
                db.session.add(template)

            db.session.commit()

        else:
            # Rename any legacy "Small Axe" names already in the DB
            _renames = {
                'Small Axe \u2014 Signal Observation': 'Opening Touch \u2014 Signal Observation',
                'Small Axe \u2014 Hypothesis':         'Second Touch \u2014 Hypothesis',
                'Small Axe \u2014 Proof':              'Third Touch \u2014 Proof / Case Study',
                'Small Axe \u2014 Soft Close':         'Soft Close \u2014 Last Attempt Before Breakup',
                'Small Axe \u2014 Breakup':            'Breakup Email \u2014 Final Touch',
            }
            changed = False
            for old, new in _renames.items():
                t = Template.query.filter_by(name=old, is_builtin=True).first()
                if t:
                    t.name = new
                    changed = True
            if changed:
                db.session.commit()
