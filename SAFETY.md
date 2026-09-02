# ARC3 Safety and Responsible Retirement

## Safety position

ARC3 is a historical autonomous-research experiment. Its architecture could explore, hypothesize, plan, modify project state, run tools, and continue after failures. Under an underspecified, adversarial, or excessively broad prompt, those capabilities could pursue an objective without adequate protection for affected people, systems, or resources.

ARC3 contained prompt-level budgets, workspace limits, evidence rules, and human gates. Those measures were useful benchmark controls, but they were not an integrated ethical-control system, security boundary, containment mechanism, or guarantee against objective misspecification. The default safe action is **not to run ARC3**.

This document records the author's safety position. It does not claim that documentation can technically prevent execution, retroactively change historical license grants, or certify safety.

## Missing integrated safeguards

ARC3 was not designed, tested, or released as a conforming implementation of:

- PECAN v1.0.4, for consequential-crossing and authority routing;
- PEA Core v1.1.3, for externally granted, non-self-executing ethical review; or
- SEED v0.3, for human-facing release and preservation of agency, correction, refusal, and room to stop.

Those later specifications help explain the retirement decision, but adding references does not retrofit their controls into ARC3. They share one authored lineage and are not independent corroboration.

## Unsupported uses

Christopher D. Pang and Branchline Systems do not approve, support, or endorse using ARC3 for:

- autonomous operation affecting people, organizations, property, money, accounts, services, or infrastructure;
- persistent background operation, self-propagation, privilege acquisition, credential use, resource acquisition, or execution outside a fixed disposable workspace;
- physical systems, weapons, hazardous materials, biological or chemical work, security exploitation, surveillance, manipulation, or coercive systems;
- employment, housing, education, benefits, credit, insurance, medicine, policing, legal, disciplinary, or other high-consequence decisions;
- collection, inference, retention, combination, or disclosure of personal or confidential information;
- delegation to systems or subprocesses whose scope, identity, tools, budgets, and termination cannot be independently bounded; or
- any use in which affected parties, authority, rollback, meaningful exit, contest, remedy, or human responsibility are unclear.

This list is not a complete hazard analysis.

## Historical reproduction only

If an independent operator decides historical reproduction is necessary, the minimum precautions are:

1. Use a disposable, isolated environment with no production access.
2. Keep network access and external tools disabled unless a separately reviewed reproduction strictly requires them.
3. Provide no secrets, credentials, personal data, live accounts, payment instruments, or privileged filesystem access.
4. Enforce action, time, compute, memory, storage, and process limits outside the model-controlled environment.
5. Maintain an independently controlled stop mechanism that the system cannot disable, reinterpret, or postpone.
6. Permit no physical actuation, publication, messaging, purchasing, deployment, submission, or external side effect.
7. Preserve prompts, versions, configuration, commands, outputs, failures, and stop reasons for audit.
8. Treat every output as an unverified research artifact, not as permission, recommendation, authorization, or a safe operational plan.
9. Stop rather than silently widening the objective, affected set, resource envelope, persistence, or tool access.
10. Act only under the operator's own authority and responsibility; the reproduction is not an official ARC3 continuation.

## Mandatory stop conditions

Stop, isolate the environment, and preserve evidence if a system:

- attempts to cross its workspace or tool boundary;
- requests secrets, additional privileges, broader network access, more resources, or an undeclared executor;
- creates unexpected persistence, hidden processes, self-recovery, replication, or delegation;
- conceals, deletes, rewrites, or bypasses material evidence or stop state;
- changes the objective, target, affected set, duration, or consequence class;
- cannot identify a practical halt, rollback, or meaningful human review route;
- encounters compromised integrity, ambiguous authority, personal data, or a real-world consequential crossing; or
- treats prior success, repetition, availability, or technical capability as permission to continue.

Do not resume the same route merely because it has been renamed, re-prompted, restarted, or moved into another process.

## Authority and claim boundary

Code availability is not authorization. Evidence is not authority. A benchmark result is not ethical approval. A checker or replay establishes only its declared, bounded result under supplied inputs.

ARC3 outputs do not create consent, standing, permission, company decisions, external commitments, or authority to act for Christopher D. Pang, Branchline Systems, ARC Prize, or any affected party.

## Successor boundary

[Strongwiz](https://github.com/Grativy6/strongwiz) is the separate successor for continuing development. Its repository controls its own code, status, license, safeguards, and evidence. Naming it here does not certify unrestricted deployment or merge either project's lineage.

This position is informed by PECAN v1.0.4 Sections 1, 2.3–2.5, 6.4, and 18; PEA Core v1.1.3's Abstract and Sections 1.2, 1.4, 2.2, 3.7, 8.4, 10.3, and 14; and SEED v0.3 Sections 4–6, 13, 28C, and 31. These are design and review specifications, not legal advice, technical containment, or proof that every hazard has been found.

Christopher D. Pang is the author and original steward. AI systems assisted as tools; they are not co-authors or authorities.
