import { CollapsibleNotice } from "@/components/Notices";

/** Aviso médico obligatorio (R7, RGPD art. 9): MyFood no da consejo médico. Se usa en
 * las pantallas donde se calculan objetivos, se generan planes o se habla de alérgenos.
 *
 * Se puede plegar: `id` es el aviso concreto en las preferencias del usuario (cada pantalla
 * el suyo) y `title` lo que queda a la vista cuando está plegado. Con `collapsible={false}`
 * va siempre entero — en el registro, donde todavía no hay cuenta en la que guardarlo y es
 * la primera vez que se lee. */
export function MedicalDisclaimer({
  id = "medical",
  title = "No es consejo médico",
  collapsible = true,
  children,
}: {
  id?: string;
  title?: string;
  collapsible?: boolean;
  children?: React.ReactNode;
}) {
  const body = children ?? (
    <>
      MyFood no da consejo médico ni diagnósticos: los cálculos y los planes son estimaciones
      orientativas. Consulta con un profesional sanitario o un dietista-nutricionista antes de
      hacer cambios relevantes en tu alimentación, y especialmente si tienes alguna patología,
      estás embarazada o eres menor de edad.
    </>
  );
  if (!collapsible) {
    return (
      <p
        role="note"
        className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200"
      >
        {body}
      </p>
    );
  }
  return (
    <CollapsibleNotice id={id} title={title}>
      {body}
    </CollapsibleNotice>
  );
}
