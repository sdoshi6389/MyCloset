import { createClient } from "@supabase/supabase-js";

const supabaseUrl = "https://gbtoavsgyzfcwgkftfko.supabase.co";
const supabaseKey = "sb_publishable_vni9u3A3Fo_J7D4_ktazlw_LOVyU8Cb";

export const supabase = createClient(supabaseUrl, supabaseKey);
