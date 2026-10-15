import { useLocation, Link } from "react-router-dom";
import { useEffect } from "react";

const NotFound = () => {
  const location = useLocation();

  useEffect(() => {
    console.error("404 Error: User attempted to access non-existent route:", location.pathname);
  }, [location.pathname]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="text-center space-y-4">
        <h1 className="text-[18px] leading-[1.35] tracking-[-0.005em] text-foreground">404</h1>
        <p className="text-[14px] leading-[1.65] text-foreground/80">Page not found</p>
        <Link to="/" className="inline-block text-[14px] text-primary hover:text-primary/80 underline underline-offset-4">
          Return home
        </Link>
      </div>
    </div>
  );
};

export default NotFound;
