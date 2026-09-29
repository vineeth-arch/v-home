-- One ritual selection per household, day and slot (weekly check-in uses slot 'weekly' on the week's Monday).
create unique index ritual_selections_household_day_slot on public.ritual_selections (household_id, day, slot);
