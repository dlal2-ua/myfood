"use client";

import { createContext, useContext } from "react";

const CurrentUserContext = createContext<string | null>(null);

/** Id del usuario autenticado para el código de cliente que no recibe el usuario por props
 * (la cola de registros sin conexión etiqueta cada registro con él). */
export function CurrentUserProvider({
  userId,
  children,
}: {
  userId: string | null;
  children: React.ReactNode;
}) {
  return <CurrentUserContext.Provider value={userId}>{children}</CurrentUserContext.Provider>;
}

export function useCurrentUserId(): string | null {
  return useContext(CurrentUserContext);
}
