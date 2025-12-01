// src/App.jsx
import React from "react";
import { Routes, Route, Navigate, Outlet, useLocation } from "react-router-dom";

import Login from "./pages/Login";
import AdminDashboard from "./components/AdminDashboard";
import GroupAdminDashboard from "./components/GroupAdminDashboard";
import InvestorDashboard from "./components/InvestorDashboard";
import OpportunityFundDashboard from "./components/OpportunityFundDashboard";
import Generalpartner from "./components/GeneralPartner";

import AcceptInvite from "./pages/AcceptInvite.jsx";
import AcceptAdminInvite from "./pages/AcceptAdminInvite.jsx";
import ForgotPassword from "./pages/ForgotPassword.jsx";
import ResetPassword from "./pages/ResetPassword.jsx";

import ChatWidget from "./components/ChatWidget";
import { AuthContext } from "./context/AuthContext";
import api from "./services/api";

/* --------- helpers --------- */

function normalizeRole(value) {
  // Makes "group admin", "GroupAdmin", etc. → "groupadmin"
  return (value || "").toString().replace(/\s+/g, "").toLowerCase();
}

/** Guard: waits for auth; redirects to /login if unauthenticated. */
function RequireAuth() {
  const { user } = React.useContext(AuthContext);
  const location = useLocation();

  if (user === undefined) return <div>Loading...</div>; // booting
  if (user === null)
    return <Navigate to="/login" replace state={{ from: location }} />;

  return <Outlet />; // authenticated children
}

/** Guard: like RequireAuth but enforces a role. */
function RequireRole({ role }) {
  const { user } = React.useContext(AuthContext);
  const location = useLocation();

  if (user === undefined) return <div>Loading...</div>;
  if (user === null)
    return <Navigate to="/login" replace state={{ from: location }} />;

  const type = normalizeRole(user.user_type);
  const required = normalizeRole(role);

  // ✅ Allow group admins to access investor-protected routes as well
  if (required === "investor" && type === "groupadmin") {
    return <Outlet />;
  }

  if (type !== required) {
    // Authenticated but wrong role → send to their own home
    if (type === "admin") return <Navigate to="/admin-dashboard" replace />;
    if (type === "groupadmin")
      // default home for group admins: investor dashboard
      return <Navigate to="/investor-dashboard" replace />;
    return <Navigate to="/investor-dashboard" replace />;
  }
  return <Outlet />;
}

export default function App() {
  const { user } = React.useContext(AuthContext);
  const location = useLocation();

  const rawUserType = user?.user_type || "";
  const userType = normalizeRole(rawUserType);

  // ---- Fetch current investor meta so we know if they are a dependent
  // Prefer any server-injected bootstrap value; otherwise fetch /api/investor/me
  const [investorMeta, setInvestorMeta] = React.useState(() => {
    const boot = typeof window !== "undefined" ? window.__INVESTOR__ : null;
    return boot || null;
  });

  React.useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!user || userType !== "investor") {
        setInvestorMeta(null);
        return;
      }
      // if server already bootstrapped it, keep it
      if (window.__INVESTOR__) {
        setInvestorMeta(window.__INVESTOR__);
        return;
      }
      try {
        const { data } = await api.get("/api/investor/me");
        if (!cancelled) {
          setInvestorMeta(data || null);
          // store for other pages that read the bootstrap var
          window.__INVESTOR__ = data || null;
        }
      } catch {
        if (!cancelled) setInvestorMeta(null);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [user?.id, userType]);

  const isDependent = React.useMemo(() => {
    if (!investorMeta) return false;
    const t = (investorMeta.investor_type || "").toLowerCase();
    // Dependent if marked "Depends/Dependent" or if it's attached to a parent
    return t.startsWith("depend") || investorMeta.parent_investor_id != null;
  }, [investorMeta]);

  // -------- Public route detection (extended with new pages) --------
  const EXACT_PUBLIC = React.useMemo(
    () =>
      new Set([
        "/login",
        "/invite/accept",
        "/accept-invite",
        "/admin/generalpartner",
        "/forgot-password",
        "/reset-password",
      ]),
    []
  );

  const isPublicExact = EXACT_PUBLIC.has(location.pathname);
  const isPublicPattern = location.pathname.startsWith("/invite/admin/"); // e.g. /invite/admin/:token
  const isPublic = isPublicExact || isPublicPattern;

  // Show chat only when:
  // - user is logged in
  // - not on a public page
  // - not an investor of dependent type
  const showChat =
    !!user && !isPublic && !(userType === "investor" && isDependent);

  /** If the user is already logged in, /login should forward them to their home. */
  function LoginRoute() {
    if (user === undefined) return <div>Loading...</div>;
    if (user === null) return <Login />;

    if (userType === "admin") return <Navigate to="/admin-dashboard" replace />;

    // ✅ Group admins land on investor dashboard by default
    if (userType === "groupadmin" || userType === "investor") {
      return <Navigate to="/investor-dashboard" replace />;
    }

    return <Navigate to="/investor-dashboard" replace />;
  }

  /** Single place that maps “/dashboard” to the user’s home. */
  function MyHome() {
    if (user === undefined) return <div>Loading...</div>;
    if (!user) return <Navigate to="/login" replace />;

    if (userType === "admin") return <Navigate to="/admin-dashboard" replace />;

    // ✅ Same rule here: group admins → investor dashboard
    if (userType === "groupadmin" || userType === "investor") {
      return <Navigate to="/investor-dashboard" replace />;
    }

    return <Navigate to="/investor-dashboard" replace />;
  }

  return (
    <>
      <Routes>
        {/* Public pages */}
        <Route path="/login" element={<LoginRoute />} />
        <Route path="/invite/accept" element={<AcceptInvite />} />
        {/* backwards-compatible alias */}
        <Route path="/accept-invite" element={<AcceptInvite />} />
        {/* admin invite accept page */}
        <Route path="/invite/admin/:token" element={<AcceptAdminInvite />} />
        {/* forgot/reset password */}
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/admin/generalpartner" element={<Generalpartner />} />

        {/* Authenticated area */}
        <Route element={<RequireAuth />}>
          {/* “/dashboard” just resolves to the correct home once */}
          <Route path="/dashboard" element={<MyHome />} />
        </Route>

        {/* Role-scoped areas */}
        <Route element={<RequireRole role="admin" />}>
          <Route path="/admin-dashboard" element={<AdminDashboard />} />
          <Route
            path="/admin/opportunity"
            element={<OpportunityFundDashboard />}
          />
        </Route>

        <Route element={<RequireRole role="groupadmin" />}>
          <Route
            path="/group-admin-dashboard"
            element={<GroupAdminDashboard />}
          />
        </Route>

        <Route element={<RequireRole role="investor" />}>
          <Route path="/investor-dashboard" element={<InvestorDashboard />} />
        </Route>

        {/* Fallback */}
        <Route path="*" element={<MyHome />} />
      </Routes>

      {showChat && (
        <ChatWidget
          user={window.__PORTAL_USER__}
          investor={window.__INVESTOR__}
          tenant="default"
          ttsDefaultEnabled={false}
          autoSendOnFinal
          defaultOpen={true}
          apiBase="/api"
        />
      )}
    </>
  );
}
