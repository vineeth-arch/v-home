import type { Idea } from './model'

/** Idea to a shared task (or a dream). The idea keeps existing and becomes 'planned'. */
export const ideaToTask = (i: Pick<Idea, 'title' | 'note'>) => ({ title: i.title.trim(), kind: 'task' as const, owner: 'both', done: false })
export const ideaToDream = (i: Pick<Idea, 'title' | 'note'>) => ({ title: i.title.trim(), why: i.note.trim(), affirmation: '', next_step: '', art: 'sun' })
