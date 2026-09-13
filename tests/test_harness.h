/*
 * Minimal test harness: no external dependency, the tests compile with a
 * plain gcc and run in a fraction of a second.
 */
#ifndef TEST_HARNESS_H
#define TEST_HARNESS_H

#include <math.h>
#include <stdio.h>
#include <string.h>

static int hb_tests_run    = 0;
static int hb_tests_failed = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        hb_tests_run++;                                                        \
        if (!(cond)) {                                                         \
            hb_tests_failed++;                                                 \
            printf("  FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond);           \
        }                                                                      \
    } while (0)

#define CHECK_EQ_INT(actual, expected)                                         \
    do {                                                                       \
        long a_ = (long)(actual);                                              \
        long e_ = (long)(expected);                                            \
        hb_tests_run++;                                                        \
        if (a_ != e_) {                                                        \
            hb_tests_failed++;                                                 \
            printf("  FAIL %s:%d  %s == %s  (got %ld, want %ld)\n", __FILE__,  \
                   __LINE__, #actual, #expected, a_, e_);                      \
        }                                                                      \
    } while (0)

#define CHECK_NEAR(actual, expected, tol)                                      \
    do {                                                                       \
        double a_ = (double)(actual);                                          \
        double e_ = (double)(expected);                                        \
        hb_tests_run++;                                                        \
        if (!(fabs(a_ - e_) <= (tol))) {                                       \
            hb_tests_failed++;                                                 \
            printf("  FAIL %s:%d  %s ~= %s  (got %.6f, want %.6f)\n",          \
                   __FILE__, __LINE__, #actual, #expected, a_, e_);            \
        }                                                                      \
    } while (0)

#define CHECK_STR(actual, expected)                                            \
    do {                                                                       \
        const char *a_ = (actual);                                             \
        const char *e_ = (expected);                                           \
        hb_tests_run++;                                                        \
        if (a_ == NULL || strcmp(a_, e_) != 0) {                               \
            hb_tests_failed++;                                                 \
            printf("  FAIL %s:%d  %s == \"%s\"  (got \"%s\")\n", __FILE__,     \
                   __LINE__, #actual, e_, a_ ? a_ : "(null)");                 \
        }                                                                      \
    } while (0)

#define RUN(fn)                                                                \
    do {                                                                       \
        printf("- %s\n", #fn);                                                 \
        fn();                                                                  \
    } while (0)

#define TEST_SUMMARY(name)                                                     \
    do {                                                                       \
        printf("%s: %d assertions, %d failure(s)\n", (name), hb_tests_run,     \
               hb_tests_failed);                                               \
        return hb_tests_failed == 0 ? 0 : 1;                                   \
    } while (0)

#endif /* TEST_HARNESS_H */
