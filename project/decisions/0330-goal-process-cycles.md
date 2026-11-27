# 0330 — Process runs in Goal cycles

Status: accepted.

An ordinary Goal can reference one Process definition. The Goals editor lists active
definitions available under the responsible agent's Process access policy. Setting a
definition requires both Goal editing and Process launch privileges. At admission, the
scheduler checks the current definition and agent access again. The start worker
rechecks access and the selected workflow before dispatch.

The Goal owns schedules and cycle history. Process owns the run and its start job.
Admission commits all three records together under the Goal lock. The Process run
UUID remains a historical reference on the cycle after Process retention.

An execution uses the process's standard start and default inputs. The run's terminal
state closes the cycle and supplies the timestamp used to schedule a delay-based Goal.
A Goal without a process uses the existing Task and monitoring path.
