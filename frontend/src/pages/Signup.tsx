import React from "react";
import SignupForm from "../components/auth/SignupForm";

const SignupPage: React.FC = () => {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        height: "100vh",
      }}
    >
      <h1>Signup</h1>
      <SignupForm />
    </div>
  );
};

export default SignupPage;
